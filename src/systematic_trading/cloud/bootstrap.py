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

REPO_URL_TEMPLATE = "https://{auth}github.com/michaellaret7/Systematic-Trading.git"

ENV_FILE = Path(__file__).parents[3] / ".env"

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

APT_SNIPPET = """
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get install -y -qq git curl
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
curl -LsSf https://astral.sh/uv/install.sh | sh
. "$HOME/.local/bin/env"

# Idempotent: a container restart re-runs the start script with the container
# disk intact, so the clone must not fail on an existing checkout.
if [ ! -d /root/repo ]; then
    git clone --branch {branch} --single-branch "{REPO_URL_TEMPLATE.format(auth="${GITHUB_TOKEN:+$GITHUB_TOKEN@}")}" /root/repo
fi
cd /root/repo
uv sync --no-dev --no-cache
"""


def log_sync_snippet(job_name: str) -> str:
    """Start the run log, memory monitor, and 5-minute S3 sync loop."""
    return f"""
STAMP=$(date -u +%Y-%m-%dT%H%M%SZ)
upload_log() {{ uv run python -c "import os, boto3; boto3.client('s3').upload_file('/root/job.log', os.environ['S3_BUCKET'], 'logs/{job_name}/$STAMP.log')"; }}
: > /root/job.log
{MONITOR_SNIPPET}
( while true; do sleep 300; upload_log; done ) &
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
    even when an earlier step fails.

    ``self_delete`` is the function definition from ``self_delete_snippet``.
    ``preamble`` is provider setup that runs after that definition and before
    the repo checkout — forwarding the environment, or guarding against a
    re-run on providers that restart the script.
    """
    return f"""#!/bin/bash
{APT_SNIPPET}
{self_delete}
{preamble}
{bootstrap_snippet(branch)}
{log_sync_snippet(job_name)}
# `tee -a`, not `tee`: the memory monitor is appending to this same file, and a
# truncating tee would overwrite its samples from offset 0.
uv run python -m {job_module} 2>&1 | tee -a /root/job.log

upload_log

# Best-effort second upload: it carries the self-delete evidence but loses the
# race if the machine is torn down first, so the run log is already safe above.
self_delete 2>&1 | tee -a /root/job.log
upload_log
"""
