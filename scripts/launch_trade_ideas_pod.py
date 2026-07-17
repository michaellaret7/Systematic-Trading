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
# Anyone can subscribe to the pubv output from the pod and log it

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

# Runs on the pod as its start command. Plain sequencing (no `set -e`): the
# log upload and self-delete must run even when an earlier step fails.
START_SCRIPT = f"""
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get install -y -qq git curl
curl -LsSf https://astral.sh/uv/install.sh | sh
. "$HOME/.local/bin/env"

git clone --branch {REPO_BRANCH} --single-branch "{REPO_URL_TEMPLATE.format(auth="${GITHUB_TOKEN:+$GITHUB_TOKEN@}")}" /root/repo
cd /root/repo
uv sync --no-dev --no-cache

STAMP=$(date -u +%Y-%m-%dT%H%M%SZ)
upload_log() {{ uv run python -c "import os, boto3; boto3.client('s3').upload_file('/root/ideas.log', os.environ['S3_BUCKET'], 'logs/trade_ideas/$STAMP.log')"; }}
touch /root/ideas.log

( while true; do sleep 300; upload_log; done ) &

uv run python -m {JOB_MODULE} 2>&1 | tee /root/ideas.log

upload_log

curl -s -X DELETE "{RUNPOD_API}/pods/$RUNPOD_POD_ID" -H "Authorization: Bearer $RUNPOD_API_KEY"
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
        "cpuFlavorIds": ["cpu3c"],
        "vcpuCount": 2,
        # 10 GB overflowed (base image + Python 3.13 + the lumibot dependency
        # tree); 20 is RunPod's max for this pod size, padded by --no-cache.
        "containerDiskInGb": 20,
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
