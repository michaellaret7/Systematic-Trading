"""Launch RunPod CPU pods that run our workloads, in one of two lifecycles.

``launch_job_pod()`` runs a finite job: the pod clones the repo, installs
dependencies with uv, runs the given job module via ``python -m``, syncs one
cumulative run log to ``s3://<S3_BUCKET>/logs/<job_name>/<stamp>/full.log`` every
five minutes (and once more at the end), streams live to CloudWatch, and then
deletes itself — on success or failure — so billing stops automatically.

``launch_strategy_pod()`` runs a live strategy forever: same bootstrap and
CloudWatch stream, but the S3 archive uploads at the top of each hour during ET
market hours (10:00-17:00), and there is no run-once guard and no self-delete. If
the strategy process exits, the container restart relaunches it (restart =
recovery) under a fresh ``<stamp>`` folder. The pod bills until ``stop_pod()`` —
or the RunPod console — deletes it.

Either launch call returns in seconds; the run continues in RunPod's cloud
with no connection to this machine.

The shared lifecycle lives in ``bootstrap``; this module holds only what is
RunPod-specific — the API payload, the run-once guard a restarting container
needs, and the restart-as-recovery strategy script.

Requires ``RUNPOD_API_KEY`` (and ``GITHUB_TOKEN`` while the repo is private)
in the environment / .env alongside the usual job credentials.
"""

from __future__ import annotations

import os

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

RUNPOD_API = "https://rest.runpod.io/v1"

# Pod size. RAM = vcpuCount x the flavor's RAM multiplier (2 GB/vCPU for the
# compute-optimized `c` tier, 4 for general-purpose `g`, 8 for memory-optimized
# `m`), and max container disk = vcpuCount x 10 GB on cpu3.
DEFAULT_CPU_FLAVOR = "cpu3g"
DEFAULT_VCPU_COUNT = 4

# 10 GB overflowed (base image + Python 3.13 + the lumibot dependency
# tree); 20 ran without headroom, and disk pressure was a suspect in the
# 2026-07-17 container deaths, so take the full allowance for this size.
DEFAULT_CONTAINER_DISK_GB = 40

# RunPod injects the pod's own id into the container environment, so no
# metadata service call is needed.
SELF_DELETE = self_delete_snippet(
    id_expr='echo "$RUNPOD_POD_ID"',
    delete_url=f"{RUNPOD_API}/pods/$id",
    token_var="RUNPOD_API_KEY",
)

# RunPod re-runs the start script whenever the container restarts, so a finite
# job must be safe to execute twice. This guards on a marker on the container
# disk (which outlives a restart): a second execution deletes the pod and exits
# instead of re-running the job. Without that guard a failed self-delete becomes
# an infinite restart loop — one ran 6,629 times over 40h on 2026-07-17,
# re-analyzing the same tickers and draining the OpenRouter balance.
RUN_ONCE_GUARD = """
if [ -f /root/.job_started ]; then
    echo "Container restarted after the job already ran — deleting pod without re-running."
    self_delete
    exit 0
fi

touch /root/.job_started
"""


#     ================================
# --> Helper funcs
#     ================================


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
        "env": env_pairs("RUNPOD_API_KEY"),
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
        f"Logs -> s3://{os.environ['S3_BUCKET']}/logs/{name}/<stamp>/full.log "
        f"and CloudWatch group '{CLOUDWATCH_LOG_GROUP}'.\n"
        f"Tail live: aws logs tail {CLOUDWATCH_LOG_GROUP} --follow --log-stream-name-prefix {name}"
    )

    return pod_id


#     ================================
# --> Start scripts
#     ================================


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
{hourly_et_upload_snippet()}
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
    script = job_script(
        job_name,
        job_module,
        branch,
        self_delete=SELF_DELETE,
        preamble=RUN_ONCE_GUARD,
    )

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

    The pod bills until ``stop_pod()`` — or the RunPod console — deletes it.
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
