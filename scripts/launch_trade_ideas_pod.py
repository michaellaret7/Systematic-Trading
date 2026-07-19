"""Launch a self-terminating RunPod CPU pod that runs the trade-ideas job.

Creates a 2 vCPU / 4 GB secure-cloud pod via the RunPod REST API. The pod
clones the repo, installs dependencies with uv, runs ``generate_trade_ideas``,
syncs the run log to ``s3://<S3_BUCKET>/logs/trade_ideas/<utc-stamp>.log``
every five minutes (and once more at the end), and then deletes itself — on
success or failure — so billing stops automatically.
The launch call returns in seconds; the run continues in RunPod's cloud with
no connection to this machine.

Requires ``RUNPOD_API_KEY`` (and ``GITHUB_TOKEN`` while the repo is private)
in the environment / .env alongside the usual job credentials.

Usage:
    uv run python scripts/launch_trade_ideas_pod.py
"""

# Build live pub sub logging infrastructure
# Anyone can subscribe to the pub output from the pod and log it

from __future__ import annotations

import os
from pathlib import Path

import requests
from dotenv import dotenv_values, load_dotenv

RUNPOD_API = "https://rest.runpod.io/v1"
REPO_URL_TEMPLATE = "https://{auth}github.com/michaellaret7/Systematic-Trading.git"
REPO_BRANCH = "dev"
JOB_MODULE = "systematic_trading.strategies.csf_champions.workflows.generate_trade_ideas"

ENV_FILE = Path(__file__).parents[1] / ".env"

# Pod size. RAM = vcpuCount x the flavor's RAM multiplier (2 GB/vCPU for the
# compute-optimized `c` tier, 4 for general-purpose `g`, 8 for memory-optimized
# `m`), and max container disk = vcpuCount x 10 GB on cpu3.
#
# The original cpu3c/2 gave 4 GB, and every one of the 30 full runs on
# 2026-07-17 died at 5-17 minutes without completing a single ticker — right as
# ~28 concurrent agent contexts (7 workers x 3 subagents) grew past it. cpu3g/4
# gives 16 GB and 40 GB of disk for $0.16/hr, a few dollars for a full run.
CPU_FLAVOR = "cpu3g"
VCPU_COUNT = 4
CONTAINER_DISK_GB = 40

# Sampled into the run log every 30s so an OOM leaves evidence. Kept out of the
# f-string below because its awk programs are brace-heavy.
MONITOR_SNIPPET = """
# Container memory lives in the cgroup, not `free` — inside a container `free`
# reports the *host's* RAM and would hide an approaching OOM kill entirely.
mem_report() {
    if [ -f /sys/fs/cgroup/memory.current ]; then
        used=$(cat /sys/fs/cgroup/memory.current 2>/dev/null)
        limit=$(cat /sys/fs/cgroup/memory.max 2>/dev/null)
        oom=$(awk '/^oom_kill /{print $2}' /sys/fs/cgroup/memory.events 2>/dev/null)
    elif [ -f /sys/fs/cgroup/memory/memory.usage_in_bytes ]; then
        used=$(cat /sys/fs/cgroup/memory/memory.usage_in_bytes 2>/dev/null)
        limit=$(cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null)
        oom=$(awk '/^oom_kill /{print $2}' /sys/fs/cgroup/memory/memory.oom_control 2>/dev/null)
    else
        echo "$(date -u +%H:%M:%S) MEM  cgroup unavailable"
        return
    fi

    # Arithmetic in bash, not awk: these are byte counts in the billions, and
    # awk implementations differ on integer width. cgroup v1 reports
    # "unlimited" as a near-2^63 sentinel, so anything absurd is unlimited too.
    used=${used:-0}

    if [ "$limit" = "max" ] || [ -z "$limit" ] || [ "$limit" -gt 1000000000000 ]; then
        budget="$((used / 1048576)) MiB / unlimited"
    else
        budget="$((used / 1048576))/$((limit / 1048576)) MiB ($((100 * used / limit))%)"
    fi

    echo "$(date -u +%H:%M:%S) MEM  $budget  oom_kills=${oom:-?}  disk=$(df -h / | awk 'NR==2 {print $5}')  procs=$(ps -e --no-headers | wc -l)"
}

# Appends straight to the log so the samples ride along to S3, and so sampling
# outlives the Python process — the last line before a kill is the evidence.
( while true; do mem_report >> /root/ideas.log; sleep 30; done ) &
"""

# Runs on the pod as its start command. Plain sequencing (no `set -e`): the
# log upload and self-delete must run even when an earlier step fails.
#
# RunPod re-runs this script whenever the container restarts, so it must be
# safe to execute twice. It guards on a marker on the container disk (which
# outlives a restart): a second execution deletes the pod and exits instead of
# re-running the job. Without that guard a failed self-delete becomes an
# infinite restart loop — one ran 6,629 times over 40h on 2026-07-17,
# re-analyzing the same tickers and draining the OpenRouter balance.
START_SCRIPT = f"""
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get install -y -qq git curl

# Retries: a single fire-and-forget DELETE leaves the pod billing if it fails.
self_delete() {{
    if [ -z "$RUNPOD_POD_ID" ]; then
        echo "FATAL: RUNPOD_POD_ID unset — cannot self-delete; stop this pod by hand."
        return 1
    fi

    for attempt in 1 2 3 4 5; do
        code=$(curl -s -o /tmp/delete.out -w '%{{http_code}}' -X DELETE "{RUNPOD_API}/pods/$RUNPOD_POD_ID" -H "Authorization: Bearer $RUNPOD_API_KEY")
        echo "self-delete attempt $attempt: HTTP $code $(cat /tmp/delete.out)"

        case "$code" in 2*) return 0;; esac

        sleep 10
    done

    echo "FATAL: self-delete failed after 5 attempts; stop this pod by hand."
    return 1
}}

if [ -f /root/.job_started ]; then
    echo "Container restarted after the job already ran — deleting pod without re-running."
    self_delete
    exit 0
fi

touch /root/.job_started

curl -LsSf https://astral.sh/uv/install.sh | sh
. "$HOME/.local/bin/env"

git clone --branch {REPO_BRANCH} --single-branch "{REPO_URL_TEMPLATE.format(auth="${GITHUB_TOKEN:+$GITHUB_TOKEN@}")}" /root/repo
cd /root/repo
uv sync --no-dev --no-cache

STAMP=$(date -u +%Y-%m-%dT%H%M%SZ)
upload_log() {{ uv run python -c "import os, boto3; boto3.client('s3').upload_file('/root/ideas.log', os.environ['S3_BUCKET'], 'logs/trade_ideas/$STAMP.log')"; }}
: > /root/ideas.log
{MONITOR_SNIPPET}
( while true; do sleep 300; upload_log; done ) &

# `tee -a`, not `tee`: the memory monitor is appending to this same file, and a
# truncating tee would overwrite its samples from offset 0.
uv run python -m {JOB_MODULE} 2>&1 | tee -a /root/ideas.log

upload_log

# Best-effort second upload: it carries the self-delete evidence but loses the
# race if the pod is torn down first, so the run log is already safe above.
self_delete 2>&1 | tee -a /root/ideas.log
upload_log
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


def pod_env() -> dict[str, str]:
    """Forward the entire .env file so the pod sees the same config as local runs."""
    if not ENV_FILE.exists():
        raise RuntimeError(f"No .env file at {ENV_FILE}.")

    env = {key: value for key, value in dotenv_values(ENV_FILE).items() if value}

    if "RUNPOD_API_KEY" not in env:
        raise RuntimeError("RUNPOD_API_KEY missing from .env — the pod needs it to self-delete.")

    return env


def launch() -> None:
    """Create the pod and print its id; the run then continues cloud-side."""
    load_dotenv(override=False)

    payload = {
        "name": "trade-ideas",
        "imageName": "runpod/base:1.0.2-ubuntu2404",
        "cloudType": "SECURE",
        "computeType": "CPU",
        "cpuFlavorIds": [CPU_FLAVOR],
        "vcpuCount": VCPU_COUNT,
        # 10 GB overflowed (base image + Python 3.13 + the lumibot dependency
        # tree); 20 ran without headroom, and disk pressure was a suspect in the
        # 2026-07-17 container deaths, so take the full allowance for this size.
        "containerDiskInGb": CONTAINER_DISK_GB,
        "volumeInGb": 0,
        "ports": ["22/tcp"],
        "env": pod_env(),
        "dockerStartCmd": ["bash", "-c", START_SCRIPT],
    }

    response = requests.post(
        f"{RUNPOD_API}/pods",
        json=payload,
        headers={"Authorization": f"Bearer {require('RUNPOD_API_KEY')}"},
        timeout=30,
    )

    if not response.ok:
        raise RuntimeError(f"RunPod launch failed ({response.status_code}): {response.text}")

    pod = response.json()

    print(f"Pod {pod.get('id')} launched — safe to shut this machine down.")
    print(
        "Log syncs to s3://"
        + os.environ["S3_BUCKET"]
        + "/logs/trade_ideas/ every 5 minutes and once more at the end."
    )


if __name__ == "__main__":
    launch()
