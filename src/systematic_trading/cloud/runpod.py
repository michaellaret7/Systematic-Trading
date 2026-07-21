"""Launch RunPod CPU pods that run our workloads, in one of two lifecycles.

``launch_job_pod()`` runs a finite job: the pod clones the repo, installs
dependencies with uv, runs the given job module via ``python -m``, syncs the
run log to ``s3://<S3_BUCKET>/logs/<job_name>/<utc-stamp>.log`` every five
minutes (and once more at the end), and then deletes itself — on success or
failure — so billing stops automatically.

``launch_strategy_pod()`` runs a live strategy forever: same bootstrap and log
sync, but no run-once guard and no self-delete. If the strategy process exits,
the container restart relaunches it (restart = recovery). The pod bills until
``stop_pod()`` — or the RunPod console — deletes it.

Either launch call returns in seconds; the run continues in RunPod's cloud
with no connection to this machine.

The bash lifecycles live here on purpose: callers parameterize only the job,
never the script, so every pod gets the same safety rails.

Requires ``RUNPOD_API_KEY`` (and ``GITHUB_TOKEN`` while the repo is private)
in the environment / .env alongside the usual job credentials.
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

ENV_FILE = Path(__file__).parents[3] / ".env"

# Pod size. RAM = vcpuCount x the flavor's RAM multiplier (2 GB/vCPU for the
# compute-optimized `c` tier, 4 for general-purpose `g`, 8 for memory-optimized
# `m`), and max container disk = vcpuCount x 10 GB on cpu3.
DEFAULT_CPU_FLAVOR = "cpu3g"
DEFAULT_VCPU_COUNT = 4

# 10 GB overflowed (base image + Python 3.13 + the lumibot dependency
# tree); 20 ran without headroom, and disk pressure was a suspect in the
# 2026-07-17 container deaths, so take the full allowance for this size.
DEFAULT_CONTAINER_DISK_GB = 40

# Sampled into the run log every 30s so an OOM leaves evidence. Kept out of the
# f-strings below because its awk programs are brace-heavy.
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


def pod_env() -> dict[str, str]:
    """Forward the entire .env file so the pod sees the same config as local runs."""
    if not ENV_FILE.exists():
        raise RuntimeError(f"No .env file at {ENV_FILE}.")

    env = {key: value for key, value in dotenv_values(ENV_FILE).items() if value}

    if "RUNPOD_API_KEY" not in env:
        raise RuntimeError("RUNPOD_API_KEY missing from .env — the pod needs it to self-delete.")

    return env


def bootstrap_snippet(branch: str) -> str:
    """Install uv and check out the repo, safely re-runnable on a container restart."""
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


def create_pod(
    name: str,
    script: str,
    cpu_flavor: str,
    vcpu_count: int,
    container_disk_gb: int,
) -> str:
    """POST the pod to RunPod and return its id."""
    load_dotenv(override=False)

    payload = {
        "name": name,
        "imageName": "runpod/base:1.0.2-ubuntu2404",
        "cloudType": "SECURE",
        "computeType": "CPU",
        "cpuFlavorIds": [cpu_flavor],
        "vcpuCount": vcpu_count,
        "containerDiskInGb": container_disk_gb,
        "volumeInGb": 0,
        "ports": ["22/tcp"],
        "env": pod_env(),
        "dockerStartCmd": ["bash", "-c", script],
    }

    response = requests.post(
        f"{RUNPOD_API}/pods",
        json=payload,
        headers={"Authorization": f"Bearer {require('RUNPOD_API_KEY')}"},
        timeout=30,
    )

    if not response.ok:
        raise RuntimeError(f"RunPod launch failed ({response.status_code}): {response.text}")

    pod_id = response.json().get("id")

    print(f"Pod {pod_id} ({name}) launched — safe to shut this machine down.")
    print(
        "Log syncs to s3://"
        + os.environ["S3_BUCKET"]
        + f"/logs/{name}/ every 5 minutes and once more per run."
    )

    return pod_id


#     ================================
# --> Start scripts
#     ================================


def start_script(job_name: str, job_module: str, branch: str) -> str:
    """Render the bash script a finite-job pod runs as its start command.

    Plain sequencing (no ``set -e``): the log upload and self-delete must run
    even when an earlier step fails.
    """
    # RunPod re-runs this script whenever the container restarts, so it must be
    # safe to execute twice. It guards on a marker on the container disk (which
    # outlives a restart): a second execution deletes the pod and exits instead of
    # re-running the job. Without that guard a failed self-delete becomes an
    # infinite restart loop — one ran 6,629 times over 40h on 2026-07-17,
    # re-analyzing the same tickers and draining the OpenRouter balance.
    return f"""
{APT_SNIPPET}
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
{bootstrap_snippet(branch)}
{log_sync_snippet(job_name)}
# `tee -a`, not `tee`: the memory monitor is appending to this same file, and a
# truncating tee would overwrite its samples from offset 0.
uv run python -m {job_module} 2>&1 | tee -a /root/job.log

upload_log

# Best-effort second upload: it carries the self-delete evidence but loses the
# race if the pod is torn down first, so the run log is already safe above.
self_delete 2>&1 | tee -a /root/job.log
upload_log
"""


def strategy_script(job_name: str, strategy_name: str, branch: str) -> str:
    """Render the bash script a run-forever strategy pod runs as its start command.

    No run-once guard and no self-delete: when the strategy process exits, this
    script ends, RunPod restarts the container, and the restart relaunches the
    strategy. Each (re)start gets its own timestamped S3 log.
    """
    return f"""
{APT_SNIPPET}
{bootstrap_snippet(branch)}
{log_sync_snippet(job_name)}
restarts=$(cat /root/.restarts 2>/dev/null || echo 0)
echo "$((restarts + 1))" > /root/.restarts
echo "run #$((restarts + 1)) of strategy {strategy_name} starting" | tee -a /root/job.log

# `tee -a`, not `tee`: the memory monitor is appending to this same file, and a
# truncating tee would overwrite its samples from offset 0.
uv run live {strategy_name} 2>&1 | tee -a /root/job.log

echo "strategy process exited — container restart will relaunch it" | tee -a /root/job.log
upload_log

# Damp a crash loop: an instantly-crashing strategy would otherwise cycle the
# container as fast as RunPod can restart it, flooding S3 with log files.
sleep 60
"""


#     ================================
# --> Public API
#     ================================


def launch_job_pod(
    job_name: str,
    job_module: str,
    *,
    branch: str = "dev",
    cpu_flavor: str = DEFAULT_CPU_FLAVOR,
    vcpu_count: int = DEFAULT_VCPU_COUNT,
    container_disk_gb: int = DEFAULT_CONTAINER_DISK_GB,
) -> str:
    """Create a self-deleting pod running ``python -m job_module`` and return its id.

    ``job_name`` names the pod in the RunPod console and the S3 log folder
    (``logs/<job_name>/``). The run continues cloud-side after this returns.
    """
    script = start_script(job_name, job_module, branch)

    return create_pod(job_name, script, cpu_flavor, vcpu_count, container_disk_gb)


def launch_strategy_pod(
    strategy_name: str,
    *,
    branch: str = "dev",
    cpu_flavor: str = DEFAULT_CPU_FLAVOR,
    vcpu_count: int = DEFAULT_VCPU_COUNT,
    container_disk_gb: int = DEFAULT_CONTAINER_DISK_GB,
) -> str:
    """Create a run-forever pod running ``uv run live strategy_name`` and return its id.

    The pod bills until deleted via ``stop_pod()`` or the RunPod console.
    Paper/live is decided by ``ALPACA_PAPER`` in the forwarded .env — this
    launcher never overrides it. Logs land in ``logs/live_<strategy_name>/``.
    """
    job_name = f"live_{strategy_name}"
    script = strategy_script(job_name, strategy_name, branch)

    return create_pod(job_name, script, cpu_flavor, vcpu_count, container_disk_gb)


def stop_pod(pod_id: str) -> None:
    """Delete a pod so billing stops. This is how a strategy pod is turned off."""
    load_dotenv(override=False)

    response = requests.delete(
        f"{RUNPOD_API}/pods/{pod_id}",
        headers={"Authorization": f"Bearer {require('RUNPOD_API_KEY')}"},
        timeout=30,
    )

    if not response.ok:
        raise RuntimeError(f"RunPod delete failed ({response.status_code}): {response.text}")

    print(f"Pod {pod_id} deleted — billing stopped.")
