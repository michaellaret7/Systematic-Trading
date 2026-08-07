"""Launch DigitalOcean Droplets that run our workloads, in one of two lifecycles.

``launch_job_droplet()`` runs a finite job: the droplet clones the repo,
installs dependencies with uv, runs the given job module via ``python -m``,
syncs one cumulative run log to
``s3://<S3_BUCKET>/logs/<job_name>/<stamp>/full.log`` every five minutes (and
once more at the end), streams live to CloudWatch, and then destroys itself —
on success or failure — so billing stops automatically.

``launch_strategy_droplet()`` runs a live strategy forever: same bootstrap and
CloudWatch stream, but the S3 archive uploads at the top of each hour during ET
market hours (10:00-17:00), and the strategy runs under a systemd unit with
``Restart=always``, so a crash relaunches it in place and a droplet reboot
brings it back. The droplet bills until ``stop_droplet()`` — or the DO console —
destroys it.

Self-destruction is an authenticated DELETE, not a poweroff: DigitalOcean keeps
billing a powered-off droplet because it holds the CPU, RAM, disk, and IP
reservation on the hypervisor. Only destroying it stops the meter.

Either launch call returns in seconds; the run continues in DO's cloud with no
connection to this machine.

The shared lifecycle lives in ``bootstrap``; this module holds only what is
DigitalOcean-specific — the API payload, the environment forwarding, and the
systemd strategy unit.

Requires ``DIGITALOCEAN_TOKEN`` (and ``GITHUB_TOKEN`` while the repo is
private) in the environment / .env alongside the usual job credentials.
"""

from __future__ import annotations

import os
import re
import shlex

import requests
from dotenv import load_dotenv

from systematic_trading.cloud.bootstrap import (
    APT_SNIPPET,
    CAPTURE_SNIPPET,
    bootstrap_snippet,
    env_pairs,
    hourly_et_upload_snippet,
    job_script,
    log_sync_snippet,
    require,
    self_delete_snippet,
)
from systematic_trading.config import CLOUDWATCH_JOB_LOG_GROUP, CLOUDWATCH_LOG_GROUP

DO_API = "https://api.digitalocean.com/v2"

# Droplet size. Slugs and live pricing come from ``GET /v2/sizes`` — `s-` is
# basic shared-CPU, `g-` general purpose (4 GB/vCPU), `c-` CPU-optimized
# (2 GB/vCPU). The `g-`/`c-` classes are gated behind an account-tier increase
# (422 "size is currently restricted"), so we stay on basic shared-CPU.
#
# Sized from measured usage, not guessed. Peaks across the S3 run logs
# (``MONITOR_SNIPPET`` samples memory every 30s) and the DO monitoring API:
# the live strategy holds 1.2 GB and ~0.5 vCPU, the trade-ideas job peaks at
# 1.6 GB, and neither has ever recorded an oom_kill. 4 GB / 2 vCPU keeps
# roughly 2.5x headroom on memory at half the price of the 8 GB size.
DEFAULT_SIZE = "s-2vcpu-4gb"
DEFAULT_REGION = "nyc3"

# Ubuntu 24.04 matches the RunPod base image, so the shared bootstrap applies
# unchanged (apt, not dnf).
DEFAULT_IMAGE = "ubuntu-24-04-x64"

# The forwarded .env on disk. Written outside the repo so it exists before the
# clone, and so systemd can read it without depending on the checkout.
ENV_PATH = "/root/machine.env"

# DigitalOcean has no env field on the create-droplet API, so the values ride
# inside user_data (64 KiB ceiling, plain text). Anyone holding the API token
# can read them back — see the module docstring in ``bootstrap`` for the shared
# rails, and prefer a secrets store before running this with real money.
SELF_DELETE = self_delete_snippet(
    id_expr="curl -s --max-time 5 http://169.254.169.254/metadata/v1/id",
    delete_url=f"{DO_API}/droplets/$id",
    token_var="DIGITALOCEAN_TOKEN",
)

# Strategy droplets only. Ubuntu's unattended-upgrades runs `needrestart`, which
# restarts every service linked against an upgraded library — and libc6/openssl
# land in nearly every security batch. On 2026-08-01 06:30 UTC it bounced
# strategy.service twice inside one dpkg run; each bounce re-entered `initialize`
# and the second submitted a second book of 25 market buys on top of a live one.
# Security patching is not worth an unattended process restart on a machine that
# places orders — a strategy droplet is short-lived and replaced, not maintained.
NO_AUTO_UPGRADE_SNIPPET = """
systemctl disable --now apt-daily.timer apt-daily-upgrade.timer unattended-upgrades 2>/dev/null || true
"""

# Strategy droplets only. The agent code sandbox needs a Docker daemon, and a
# droplet is a real VM so it can host one. This has no RunPod equivalent: pods
# are already containers and SECURE cloud denies privileged mode, so the sandbox
# exists on the DigitalOcean path alone.
#
# `docker.io` from Ubuntu's archive rather than Docker's convenience script,
# which adds a third-party apt source for an engine we have no need of — the
# sandbox uses `docker run` with resource flags and nothing version-sensitive.
DOCKER_SNIPPET = """
apt-get install -y -qq docker.io
systemctl enable --now docker
echo "docker=$(docker --version 2>/dev/null || echo MISSING)"
"""

# Where the sandbox snapshot lands. Must match the default in
# ``config.sandbox_data_dir``, which is what the tool reads.
SANDBOX_DATA_DIR = "/root/sandbox-data"


# ====================================
# --> Agent code sandbox
# ====================================


def sandbox_snippet() -> str:
    """Build the sandbox image and stage the read-only data snapshot it mounts.

    Runs after the checkout: the Dockerfile lives in the repo, and the snapshot
    needs the S3 credentials ``env_snippet`` exported.

    The snapshot exists so the sandbox can run with ``--network none`` — the
    agent's code reads parquet already on disk instead of holding S3
    credentials. It is refreshed daily because a strategy droplet lives for
    weeks while ``push_daily_prices`` and ``push_fundamentals`` rewrite these
    objects, and research against month-old bars is worse than no research.

    ``aws``, not ``uv run``: same reason as ``APT_SNIPPET``. The refresh must
    keep working when the project venv does not.
    """
    return f"""
docker build -q -t sandbox /root/repo/src/systematic_trading/agents/shared_tools/sandbox
echo "=== sandbox image build rc=$? ==="

# Flattened into one directory (see sandbox/sync.py SNAPSHOT, the authority on
# this layout) so the agent's code never reasons about repository prefixes.
# `sync` for the statements so a daily refresh re-pulls only what changed;
# universe.csv is excluded because the sandbox has no use for it.
stage_sandbox_data() {{
    mkdir -p {SANDBOX_DATA_DIR}
    aws s3 cp "s3://$S3_BUCKET/prices/daily_ohclv.parquet" {SANDBOX_DATA_DIR}/prices.parquet --only-show-errors
    aws s3 cp "s3://$S3_BUCKET/screeners/fundamentals_panel.parquet" {SANDBOX_DATA_DIR}/fundamentals_panel.parquet --only-show-errors
    aws s3 sync "s3://$S3_BUCKET/fundamentals/" {SANDBOX_DATA_DIR}/ --exclude "*" --include "*.parquet" --only-show-errors
    echo "sandbox snapshot: $(du -sh {SANDBOX_DATA_DIR} | cut -f1) across $(ls {SANDBOX_DATA_DIR} | wc -l) files"
}}

stage_sandbox_data

( while true; do sleep 86400; stage_sandbox_data; done ) &
"""


# ====================================
# --> Helper funcs
# ====================================


def env_snippet() -> str:
    """Export the whole .env and write it to disk for systemd to read.

    Exports alone are enough for the job path — ``config.load_dotenv`` runs
    with ``override=False``, so real environment variables win and no .env file
    is needed. The file exists for the strategy unit's ``EnvironmentFile``.
    """
    pairs = env_pairs("DIGITALOCEAN_TOKEN")

    # shlex.quote, not repr: repr quotes `it's` with double quotes, and bash
    # expands $ and backticks inside those — a secret containing both would be
    # mangled or executed.
    exports = "\n".join(f"export {key}={shlex.quote(value)}" for key, value in pairs.items())
    written = "\n".join(f"{key}={value}" for key, value in pairs.items())

    return f"""
{exports}

cat > {ENV_PATH} <<'ENVEOF'
{written}
ENVEOF
chmod 600 {ENV_PATH}
"""


def hostname(name: str) -> str:
    """Convert a job name to a legal droplet hostname (a-z, A-Z, 0-9, `.`, `-`).

    Our job names use underscores (``live_btc_ticker``); DigitalOcean rejects
    them. Only the hostname is rewritten — log paths keep the original name.
    """
    return re.sub(r"[^a-zA-Z0-9.-]", "-", name)


def create_droplet(
    name: str,
    script: str,
    size: str,
    region: str,
    image: str,
    log_group: str = CLOUDWATCH_LOG_GROUP,
    *,
    backups: bool = False,
) -> int:
    """POST the droplet to DigitalOcean and return its id.

    ``log_group`` only shapes the printed tail command — the script's own
    exports decide where logs actually go. It is a parameter so the two do not
    drift: jobs stream to a different group than strategies, and a hardcoded
    name here printed a command that tailed an empty group.

    ``backups`` enables DigitalOcean automated backups for persistent droplets.
    It defaults off because finite job droplets destroy themselves after running.
    """
    load_dotenv(override=False)

    payload = {
        "name": hostname(name),
        "region": region,
        "size": size,
        "image": image,
        "user_data": script,
        "monitoring": True,
        "backups": backups,
        "ipv6": False,
        "tags": ["systematic-trading", name],
    }

    response = requests.post(
        f"{DO_API}/droplets",
        json=payload,
        headers={"Authorization": f"Bearer {require('DIGITALOCEAN_TOKEN')}"},
        timeout=30,
    )

    if not response.ok:
        raise RuntimeError(f"DigitalOcean launch failed ({response.status_code}): {response.text}")

    droplet_id = response.json()["droplet"]["id"]

    print(f"Droplet {droplet_id} ({name}) launched — safe to shut this machine down.")
    print(
        f"Logs -> s3://{os.environ['S3_BUCKET']}/logs/{name}/<stamp>/full.log "
        f"and CloudWatch group '{log_group}'.\n"
        f"Tail live: aws logs tail {log_group} --follow --log-stream-name-prefix {name}"
    )

    return droplet_id


# ====================================
# --> Start scripts
# ====================================


def strategy_user_data(job_name: str, strategy_name: str, branch: str) -> str:
    """Render the cloud-init script a run-forever strategy droplet boots into.

    The strategy runs under systemd rather than inline: ``Restart=always``
    relaunches it when it exits, and ``enable`` brings it back after a droplet
    reboot without re-running the bootstrap. cloud-init runs user_data once per
    droplet, so a reboot would otherwise leave nothing to restart the strategy.

    Automatic upgrades are disabled first (see ``NO_AUTO_UPGRADE_SNIPPET``) so
    nothing outside this script can bounce the unit.

    Docker and the agent code sandbox are set up here too — the strategy's
    research agent runs its analysis inside a container on this droplet.
    """
    return f"""#!/bin/bash
{CAPTURE_SNIPPET}
{APT_SNIPPET}
{NO_AUTO_UPGRADE_SNIPPET}
{DOCKER_SNIPPET}
{env_snippet()}
{bootstrap_snippet(branch)}
{sandbox_snippet()}
{log_sync_snippet(job_name)}
{hourly_et_upload_snippet()}

cat > /etc/systemd/system/strategy.service <<'UNITEOF'
[Unit]
Description=live {strategy_name}
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/root/repo
EnvironmentFile={ENV_PATH}
# Per-boot CloudWatch target (log_sync_snippet writes it); systemd does not
# inherit the cloud-init shell's exports, so the strategy reads it from here.
EnvironmentFile=/root/cloudwatch.env
# `tee -a`, not `tee`: the memory monitor is appending to this same file, and a
# truncating tee would overwrite its samples from offset 0.
ExecStart=/bin/bash -lc '/root/.local/bin/uv run live {strategy_name} 2>&1 | tee -a /root/job.log'
Restart=always
# Damp a crash loop: an instantly-crashing strategy would otherwise cycle as
# fast as systemd can restart it, flooding S3 with log files.
RestartSec=60

[Install]
WantedBy=multi-user.target
UNITEOF

systemctl daemon-reload
systemctl enable --now strategy.service
"""


# ====================================
# --> Public API
# ====================================


def launch_job_droplet(
    job_name: str,
    job_module: str,
    *,
    branch: str = "dev",
    size: str = DEFAULT_SIZE,
    region: str = DEFAULT_REGION,
    image: str = DEFAULT_IMAGE,
) -> int:
    """Create a self-destroying droplet running ``python -m job_module``.

    ``job_name`` names the droplet in the DO console and the S3 log folder
    (``logs/<job_name>/``). The run continues cloud-side after this returns.

    No run-once guard is needed here: cloud-init runs user_data once per
    droplet, unlike RunPod's start script which re-runs on every container
    restart.
    """
    script = job_script(
        job_name,
        job_module,
        branch,
        self_delete=SELF_DELETE,
        preamble=env_snippet(),
    )

    return create_droplet(job_name, script, size, region, image, CLOUDWATCH_JOB_LOG_GROUP)


def launch_strategy_droplet(
    strategy_name: str,
    *,
    branch: str = "dev",
    size: str = DEFAULT_SIZE,
    region: str = DEFAULT_REGION,
    image: str = DEFAULT_IMAGE,
) -> int:
    """Create a run-forever droplet running ``uv run live strategy_name``.

    The droplet bills until ``stop_droplet()`` or the DO console destroys it.
    Paper/live is decided by ``ALPACA_PAPER`` in the forwarded .env — this
    launcher never overrides it. DigitalOcean automated backups are enabled.
    Logs land in ``logs/live_<strategy_name>/``.
    """
    job_name = f"live_{strategy_name}"
    script = strategy_user_data(job_name, strategy_name, branch)

    return create_droplet(job_name, script, size, region, image, backups=True)


def stop_droplet(droplet_id: int) -> None:
    """Destroy a droplet so billing stops. This is how a strategy is turned off.

    Powering off is not enough — DigitalOcean bills a powered-off droplet.
    """
    load_dotenv(override=False)

    response = requests.delete(
        f"{DO_API}/droplets/{droplet_id}",
        headers={"Authorization": f"Bearer {require('DIGITALOCEAN_TOKEN')}"},
        timeout=30,
    )

    if not response.ok:
        raise RuntimeError(f"DigitalOcean delete failed ({response.status_code}): {response.text}")

    print(f"Droplet {droplet_id} destroyed — billing stopped.")
