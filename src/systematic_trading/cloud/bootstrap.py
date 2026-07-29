"""Provider-agnostic pieces of a cloud run: .env forwarding and start-script bash.

Nothing here knows about RunPod or DigitalOcean. Every launcher renders the
same lifecycle — install uv, check out the repo, start the log sync and memory
monitor, run the work, upload the log, delete the machine — and only the
provider API and the machine's own identity differ.

The bash lives here because it encodes safety rails learned from real
incidents: container-aware memory sampling (an OOM must leave evidence), the
non-truncating ``tee -a`` (a truncating tee erases the monitor's samples), and
the retried self-delete (one fire-and-forget DELETE leaves a machine billing).
Duplicating those per provider means a fix reaches one launcher and silently
misses the other.

Requires ``GITHUB_TOKEN`` in the forwarded environment while the repo is
private, and ``S3_BUCKET`` for the log sync.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

from systematic_trading.config import CLOUDWATCH_JOB_LOG_GROUP, CLOUDWATCH_LOG_GROUP

REPO_URL_TEMPLATE = "https://{auth}github.com/michaellaret7/Systematic-Trading.git"

ENV_FILE = Path(__file__).parents[3] / ".env"

# Hard ceiling on a finite job's runtime. ``self_delete`` runs only after the job
# process exits, so any hang — a deadlocked future, a stalled socket, an agent
# that never returns — bills the machine indefinitely. This guarantees the
# process ends: TERM first so Python can flush its logs, SIGKILL if it ignores
# that. An exit code of 124 marks a timeout kill rather than a clean finish.
# A full generate_trade_ideas run takes ~2.5h, so this is slack, not a budget.
JOB_TIMEOUT = "4h"
JOB_KILL_AFTER = "5m"

# Sampled into the run log every 30s so an OOM leaves evidence. Kept out of the
# f-strings below because its awk programs are brace-heavy.
MONITOR_SNIPPET = """
# Two different truths depending on where this runs. Inside a container, memory
# lives in the cgroup and `free` reports the *host's* RAM — it would hide an
# approaching OOM kill entirely. On a plain VM the root cgroup reports no limit
# ("max" on v2, a near-2^63 sentinel on v1) and `free` is the real budget. So:
# prefer the cgroup, fall back to `free` when the cgroup says unlimited.
mem_report() {
    used=""
    limit=""
    oom=""

    if [ -f /sys/fs/cgroup/memory.current ]; then
        used=$(cat /sys/fs/cgroup/memory.current 2>/dev/null)
        limit=$(cat /sys/fs/cgroup/memory.max 2>/dev/null)
        oom=$(awk '/^oom_kill /{print $2}' /sys/fs/cgroup/memory.events 2>/dev/null)
    elif [ -f /sys/fs/cgroup/memory/memory.usage_in_bytes ]; then
        used=$(cat /sys/fs/cgroup/memory/memory.usage_in_bytes 2>/dev/null)
        limit=$(cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null)
        oom=$(awk '/^oom_kill /{print $2}' /sys/fs/cgroup/memory/memory.oom_control 2>/dev/null)
    fi

    # Arithmetic in bash, not awk: these are byte counts in the billions, and
    # awk implementations differ on integer width.
    if [ -z "$limit" ] || [ "$limit" = "max" ] || [ "$limit" -gt 1000000000000 ] 2>/dev/null; then
        budget=$(free -m | awk 'NR==2 {printf "%d/%d MiB (%d%%)", $3, $2, 100*$3/$2}')
    else
        used=${used:-0}
        budget="$((used / 1048576))/$((limit / 1048576)) MiB ($((100 * used / limit))%)"
    fi

    echo "$(date -u +%H:%M:%S) MEM  $budget  oom_kills=${oom:-?}  disk=$(df -h / | awk 'NR==2 {print $5}')  procs=$(ps -e --no-headers | wc -l)"
}

# Appends straight to the log so the samples ride along to S3, and so sampling
# outlives the Python process — the last line before a kill is the evidence.
( while true; do mem_report >> /root/job.log; sleep 30; done ) &
"""

# Must be the first thing every start script runs. Until 2026-07-28 the run log
# was created *after* the repo checkout, so apt, uv, git clone and `uv sync`
# wrote only to the provider's own console — which dies with the machine. Five
# job droplets failed inside `uv sync` and left no evidence anywhere.
#
# `exec > >(tee -a ...)` redirects the whole rest of the script, so every later
# command is captured without needing its own pipe. `tee -a`, never `tee`: the
# memory monitor appends to this same file.
CAPTURE_SNIPPET = """
: > /root/job.log
exec > >(tee -a /root/job.log) 2>&1
echo "=== boot $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
"""

APT_SNIPPET = """
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get install -y -qq git curl unzip tzdata

# The AWS CLI is installed from Amazon's own bundle, not apt: Ubuntu 24.04 has
# no `awscli` candidate ("E: Package 'awscli' has no installation candidate"),
# and it must not come from the project venv either — it is what uploads the run
# log, and a log upload that runs through `uv` dies with the very environment it
# exists to report on. Five job droplets failed silently that way on 2026-07-28.
if ! command -v aws >/dev/null; then
    curl -sSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
    unzip -q /tmp/awscliv2.zip -d /tmp
    /tmp/aws/install --update
fi
echo "aws=$(command -v aws || echo MISSING)"
"""


#     ================================
# --> Helper funcs
#     ================================


def require(name: str) -> str:
    """Return the env var's value or fail the launch before spending money."""
    value = os.getenv(name)

    if not value:
        raise RuntimeError(f"Missing required environment variable {name!r}.")

    return value


def env_pairs(required: str) -> dict[str, str]:
    """The whole .env as a dict so the machine sees the same config as local runs.

    ``required`` names the provider credential the machine needs to delete
    itself; a launch missing it would bill forever, so it fails here instead.
    """
    if not ENV_FILE.exists():
        raise RuntimeError(f"No .env file at {ENV_FILE}.")

    env = {key: value for key, value in dotenv_values(ENV_FILE).items() if value}

    if required not in env:
        raise RuntimeError(f"{required} missing from .env — the machine needs it to self-delete.")

    return env


#     ================================
# --> Bash snippets
#     ================================


def bootstrap_snippet(branch: str) -> str:
    """Install uv and check out the repo, safely re-runnable on a restart."""
    return f"""
# cloud-init executes user_data with HOME *unset*. uv's installer still writes to
# /root/.local/bin, but `. "$HOME/.local/bin/env"` then sources `/.local/bin/env`,
# which does not exist — so uv never reaches PATH and every later `uv` call dies
# with "command not found". That killed five job droplets silently on 2026-07-28:
# `uv sync` failed, the job never ran, and the log upload (which also went through
# `uv`) failed too, so nothing reached S3, CloudWatch, or Langfuse. Set HOME first
# and put the bin dir on PATH directly; do not trust the generated env script.
export HOME="${{HOME:-/root}}"
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# Idempotent: a container restart re-runs the start script with the container
# disk intact, so the clone must not fail on an existing checkout.
if [ ! -d /root/repo ]; then
    git clone --branch {branch} --single-branch "{REPO_URL_TEMPLATE.format(auth="${GITHUB_TOKEN:+$GITHUB_TOKEN@}")}" /root/repo
fi
cd /root/repo
uv sync --no-dev --no-cache
"""


def log_sync_snippet(job_name: str, *, group: str = CLOUDWATCH_LOG_GROUP) -> str:
    """Start the run log and memory monitor, and wire the S3 + CloudWatch targets.

    **One cumulative S3 object per pod.** ``job.log`` only ever grows (``tee -a``),
    so every ``upload_log`` replaces ``logs/<job_name>/<stamp>/full.log`` with the
    whole log so far — the newest object is line 1 to the last upload. A fresh pod
    gets a fresh ``<stamp>`` folder, so past pods' logs persist untouched.

    ``cloudwatch.env`` carries the per-boot log group/stream to systemd-run
    strategies (DigitalOcean), which read it via ``EnvironmentFile`` rather than
    inheriting this shell's exports; inline runs (RunPod, and finite jobs) inherit
    the exports directly. The Python handler attaches only when
    ``CLOUDWATCH_LOG_GROUP`` is present, so this is what turns real-time streaming
    on in the cloud.

    This starts the log and the memory monitor but no upload loop — callers append
    the cadence they want (``hourly_et_upload_snippet`` / ``periodic_upload_snippet``).
    """
    return f"""
STAMP=$(date -u +%Y-%m-%dT%H%M%SZ)
export S3_KEY="logs/{job_name}/$STAMP/full.log"

export CLOUDWATCH_LOG_GROUP="{group}"
export CLOUDWATCH_LOG_STREAM="{job_name}/$STAMP"

# Persist the per-boot CloudWatch target for systemd-run strategies, which read
# it via EnvironmentFile rather than inheriting this shell's exports.
cat > /root/cloudwatch.env <<CWEOF
CLOUDWATCH_LOG_GROUP={group}
CLOUDWATCH_LOG_STREAM={job_name}/$STAMP
CWEOF

# `aws`, not `uv run python`: see APT_SNIPPET. This must work even when the
# project venv does not, because that is exactly when the log matters most.
upload_log() {{ aws s3 cp /root/job.log "s3://$S3_BUCKET/$S3_KEY" --only-show-errors || echo "upload_log FAILED (rc=$?)"; }}
{MONITOR_SNIPPET}
"""


def periodic_upload_snippet(interval_seconds: int = 300) -> str:
    """Upload the run log to S3 on a fixed interval — for finite, self-deleting jobs.

    Frequent uploads bound how much a crash or OOM can lose before the guaranteed
    end-of-run upload; a short job that never completes an interval still gets that
    final upload.
    """
    return f"""
( while true; do sleep {interval_seconds}; upload_log; done ) &
"""


def hourly_et_upload_snippet() -> str:
    """Upload the run log to S3 at the top of each hour, 10:00–17:00 America/New_York.

    Eight uploads a trading day, DST-aware via ``TZ`` (``tzdata`` is installed in
    ``APT_SNIPPET``). The loop sleeps to the next top-of-hour and uploads only
    inside the window, so off-hours cost nothing. One cumulative object per pod
    means each upload simply refreshes it (see ``log_sync_snippet``). Real-time
    coverage between uploads comes from the CloudWatch stream.
    """
    return """
# Top-of-hour S3 uploads during ET market hours (10:00-17:00, DST-aware). The
# cumulative object is refreshed, not appended — see log_sync_snippet. `10#`
# forces base-10 so a zero-padded hour like 09 is not read as octal.
(
    while true; do
        now=$(date +%s)
        next=$(( (now / 3600 + 1) * 3600 ))
        sleep $(( next - now ))

        hour=$((10#$(TZ=America/New_York date +%H)))

        if [ "$hour" -ge 10 ] && [ "$hour" -le 17 ]; then
            upload_log
        fi
    done
) &
"""


def self_delete_snippet(*, id_expr: str, delete_url: str, token_var: str) -> str:
    """Define a ``self_delete`` bash function that destroys this machine.

    ``id_expr`` is bash that echoes the machine's own id (an env var the
    provider injects, or a curl against its metadata service); ``delete_url``
    is the provider's delete endpoint and may reference ``$id``.

    Retries: a single fire-and-forget DELETE leaves the machine billing if it
    fails. Defining the function is free — callers decide when to invoke it.
    """
    return f"""
self_delete() {{
    id=$({id_expr})

    if [ -z "$id" ]; then
        echo "FATAL: no machine id available — cannot self-delete; stop this machine by hand."
        return 1
    fi

    for attempt in 1 2 3 4 5; do
        code=$(curl -s -o /tmp/delete.out -w '%{{http_code}}' -X DELETE "{delete_url}" -H "Authorization: Bearer ${token_var}")
        echo "self-delete attempt $attempt: HTTP $code $(cat /tmp/delete.out)"

        case "$code" in 2*) return 0;; esac

        sleep 10
    done

    echo "FATAL: self-delete failed after 5 attempts; stop this machine by hand."
    return 1
}}
"""


#     ================================
# --> Start scripts
#     ================================


def job_script(
    job_name: str,
    job_module: str,
    branch: str,
    *,
    self_delete: str,
    preamble: str = "",
) -> str:
    """Render the finite-job lifecycle: bootstrap, run, upload, self-delete.

    Plain sequencing (no ``set -e``): the log upload and self-delete must run
    even when an earlier step fails. The job itself runs under ``timeout``
    (``JOB_TIMEOUT``) so a hang cannot keep the machine billing forever.

    ``self_delete`` is the function definition from ``self_delete_snippet``.
    ``preamble`` is provider setup that runs after that definition and before
    the repo checkout — forwarding the environment, or guarding against a
    re-run on providers that restart the script.
    """
    return f"""#!/bin/bash
{CAPTURE_SNIPPET}
{APT_SNIPPET}
{self_delete}
{preamble}
{bootstrap_snippet(branch)}
{log_sync_snippet(job_name, group=CLOUDWATCH_JOB_LOG_GROUP)}

# Upload before the job runs. Everything above — apt, clone, `uv sync` — is the
# part that used to fail invisibly, so its log must reach S3 whether or not the
# job itself ever starts.
echo "=== bootstrap complete, starting {job_module} ==="
upload_log

{periodic_upload_snippet()}
# No pipe needed: CAPTURE_SNIPPET already tees this script's whole output.
# `timeout` is the backstop that makes self-delete unconditional — see JOB_TIMEOUT.
timeout --signal=TERM --kill-after={JOB_KILL_AFTER} {JOB_TIMEOUT} uv run python -m {job_module}
echo "=== job exited rc=$? ==="

upload_log

# Best-effort second upload: it carries the self-delete evidence but loses the
# race if the machine is torn down first, so the run log is already safe above.
self_delete
upload_log
"""
