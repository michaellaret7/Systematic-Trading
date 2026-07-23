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
import shlex

import requests
from dotenv import load_dotenv

from systematic_trading.cloud.bootstrap import (
    APT_SNIPPET,
    bootstrap_snippet,
    env_pairs,
    hourly_et_upload_snippet,
    job_script,
    log_sync_snippet,
    require,
    self_delete_snippet,
)
from systematic_trading.config import CLOUDWATCH_LOG_GROUP

DO_API = "https://api.digitalocean.com/v2"

# Droplet size. Slugs and live pricing come from ``GET /v2/sizes`` — `s-` is
# basic shared-CPU, `g-` general purpose (4 GB/vCPU), `c-` CPU-optimized
# (2 GB/vCPU). g-4vcpu-16gb matches the RunPod cpu3g pod at vcpuCount=4.
DEFAULT_SIZE = "g-4vcpu-16gb"
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


#     ================================
# --> Helper funcs
#     ================================


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


def create_droplet(name: str, script: str, size: str, region: str, image: str) -> int:
    """POST the droplet to DigitalOcean and return its id."""
    load_dotenv(override=False)

    payload = {
        "name": name,
        "region": region,
        "size": size,
        "image": image,
        "user_data": script,
        "monitoring": True,
        "backups": False,
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
        f"and CloudWatch group '{CLOUDWATCH_LOG_GROUP}'.\n"
        f"Tail live: aws logs tail {CLOUDWATCH_LOG_GROUP} --follow --log-stream-name-prefix {name}"
    )

    return droplet_id


#     ================================
# --> Start scripts
#     ================================


def strategy_user_data(job_name: str, strategy_name: str, branch: str) -> str:
    """Render the cloud-init script a run-forever strategy droplet boots into.

    The strategy runs under systemd rather than inline: ``Restart=always``
    relaunches it when it exits, and ``enable`` brings it back after a droplet
    reboot without re-running the bootstrap. cloud-init runs user_data once per
    droplet, so a reboot would otherwise leave nothing to restart the strategy.
    """
    return f"""#!/bin/bash
{APT_SNIPPET}
{env_snippet()}
{bootstrap_snippet(branch)}
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
ExecStart=/bin/bash -lc 'uv run live {strategy_name} 2>&1 | tee -a /root/job.log'
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


#     ================================
# --> Public API
#     ================================


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

    return create_droplet(job_name, script, size, region, image)


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
    launcher never overrides it. Logs land in ``logs/live_<strategy_name>/``.
    """
    job_name = f"live_{strategy_name}"
    script = strategy_user_data(job_name, strategy_name, branch)

    return create_droplet(job_name, script, size, region, image)


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
