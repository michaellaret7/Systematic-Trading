"""Bisect where a job droplet dies, by uploading a marker to S3 after each step.

Five job droplets have failed at ~135s leaving nothing in S3, CloudWatch, or
Langfuse, and the account has no SSH keys so none of them could be inspected.
This probe replaces the job with the bootstrap alone and uploads the probe log
after every step, so the last marker present in S3 names the step that failed.

Deliberately does NOT use ``job_script`` — the point is to test that machinery,
not to depend on it. Reads markers back with::

    aws s3 ls s3://<bucket>/logs/_probe/ --recursive
    aws s3 cp s3://<bucket>/logs/_probe/probe.log -

Self-deletes on every path so a failed probe cannot bill.

Usage:
    uv run python scripts/launch_bootstrap_probe.py
"""

from systematic_trading.cloud.bootstrap import env_pairs
from systematic_trading.cloud.digitalocean import (
    DEFAULT_IMAGE,
    DEFAULT_REGION,
    SELF_DELETE,
    create_droplet,
    env_snippet,
)

# Same size the smoke test used, so the probe reproduces its conditions rather
# than a friendlier version of them.
SIZE = "s-1vcpu-2gb"

# Marker upload runs through the system aws, not the project venv, so it keeps
# working after the step that breaks the venv — that is the whole point.
PROBE = """
mark() {
    echo "=== $1 | $(date -u +%H:%M:%S) | mem=$(free -m | awk 'NR==2{print $3"/"$2"MB"}') disk=$(df -h / | awk 'NR==2{print $5}') ==="
    aws s3 cp /root/probe.log "s3://$S3_BUCKET/logs/_probe/probe.log" --only-show-errors 2>/dev/null
}

echo "STEP 0 reached user_data"
apt-get update -qq && apt-get install -y -qq git curl awscli tzdata
echo "STEP 1 apt rc=$?  aws=$(command -v aws || echo MISSING)  git=$(command -v git || echo MISSING)"
mark "after apt"

curl -LsSf https://astral.sh/uv/install.sh | sh
. "$HOME/.local/bin/env"
echo "STEP 2 uv rc=$?  uv=$(command -v uv || echo MISSING)"
mark "after uv"

git clone --branch dev --single-branch "https://${GITHUB_TOKEN:+$GITHUB_TOKEN@}github.com/michaellaret7/Systematic-Trading.git" /root/repo
echo "STEP 3 clone rc=$?"
mark "after clone"

cd /root/repo
uv sync --no-dev --no-cache
echo "STEP 4 uv sync rc=$?"
mark "after uv sync"

uv run python -c "import systematic_trading.cloud.smoke_test; print('import OK')"
echo "STEP 5 import rc=$?"
mark "after import"

echo "PROBE COMPLETE — every step survived"
mark "complete"
"""


if __name__ == "__main__":
    # Fail before spending money if .env cannot self-delete the droplet.
    env_pairs("DIGITALOCEAN_TOKEN")

    script = f"""#!/bin/bash
exec > >(tee -a /root/probe.log) 2>&1
{SELF_DELETE}
{env_snippet()}
{PROBE}
self_delete
"""

    droplet_id = create_droplet("bootstrap-probe", script, SIZE, DEFAULT_REGION, DEFAULT_IMAGE)

    print(f"\nprobe droplet {droplet_id} — read markers with:")
    print("  aws s3 cp s3://fundamental-screener-data/logs/_probe/probe.log -")
