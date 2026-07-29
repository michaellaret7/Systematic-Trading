"""Bisect where a cloud droplet's bootstrap dies, by marking progress to S3.

When a job droplet fails, it self-deletes and takes its evidence with it, and
the account has no SSH keys to log in with. This probe runs the *real*
``APT_SNIPPET`` and ``bootstrap_snippet`` and uploads a marker between each one,
so the last marker present in S3 names the step that failed.

Two rules make it work, both learned the hard way on 2026-07-28:

- **The marker channel must share nothing with what it measures.** The first
  version marked with ``aws s3 cp``, which apt was supposed to install — apt
  failed, so every marker failed, and the probe was as blind as the job. This
  version uploads with ``curl`` to a presigned URL: curl is preinstalled and the
  URL carries its own credentials, so step 0 reports before anything is touched.
- **Never wait on cloud-init.** ``cloud-init status --wait`` deadlocks here,
  because this script *is* cloud-init; it burns its timeout and tells you
  nothing.

Read the markers back with::

    aws s3 cp s3://<bucket>/logs/_probe/probe.log -

Self-deletes on every path, so a failed probe cannot bill.

Usage:
    uv run python scripts/launch_bootstrap_probe.py
"""

import boto3

from systematic_trading.cloud.bootstrap import APT_SNIPPET, bootstrap_snippet, env_pairs
from systematic_trading.cloud.digitalocean import (
    DEFAULT_IMAGE,
    DEFAULT_REGION,
    SELF_DELETE,
    create_droplet,
    env_snippet,
)
from systematic_trading.config import aws_region, s3_bucket

BRANCH = "dev"
JOB_MODULE = "systematic_trading.cloud.smoke_test"

# Same size the real jobs use, so the probe reproduces their conditions rather
# than a friendlier version of them.
SIZE = "s-1vcpu-2gb"

PROBE_KEY = "logs/_probe/probe.log"

# An hour covers any bootstrap worth probing; the URL dies with it.
URL_TTL_SECONDS = 3600


#     ================================
# --> Helper funcs
#     ================================


def presigned_put_url() -> str:
    """A URL that lets the droplet PUT its probe log with no credentials of its own."""
    client = boto3.client("s3", region_name=aws_region())

    return client.generate_presigned_url(
        "put_object",
        Params={"Bucket": s3_bucket(), "Key": PROBE_KEY},
        ExpiresIn=URL_TTL_SECONDS,
    )


def probe_script(put_url: str) -> str:
    """Render the probe: real bootstrap snippets, with a marker between each."""
    return f"""#!/bin/bash
: > /root/probe.log
exec > >(tee -a /root/probe.log) 2>&1

PUT_URL='{put_url}'

# curl only — preinstalled, and the presigned URL carries its own auth. Nothing
# here depends on a step this probe is meant to measure.
mark() {{
    echo "=== $1 | $(date -u +%H:%M:%S) | mem=$(free -m | awk 'NR==2{{print $3"/"$2"MB"}}') disk=$(df -h / | awk 'NR==2{{print $5}}') ==="
    curl -s -X PUT --upload-file /root/probe.log "$PUT_URL" -o /dev/null
}}

echo "STEP 0 | user_data executing | HOME='$HOME'"
echo "  preinstalled: curl=$(command -v curl || echo MISSING) git=$(command -v git || echo MISSING)"
mark "step0 boot"

{SELF_DELETE}
{env_snippet()}

{APT_SNIPPET}
echo "STEP 1 | apt rc=$?  aws=$(command -v aws || echo MISSING)  unzip=$(command -v unzip || echo MISSING)"
mark "step1 apt"

{bootstrap_snippet(BRANCH)}
echo "STEP 2 | bootstrap rc=$?  uv=$(command -v uv || echo MISSING)  HOME='$HOME'"
mark "step2 bootstrap"

uv run python -c "import {JOB_MODULE}; print('import OK')"
echo "STEP 3 | import rc=$?"
mark "step3 import"

echo "PROBE COMPLETE — every step survived"
mark "complete"

self_delete
"""


if __name__ == "__main__":
    # Fail before spending money if .env cannot self-delete the droplet.
    env_pairs("DIGITALOCEAN_TOKEN")

    droplet_id = create_droplet(
        "bootstrap-probe", probe_script(presigned_put_url()), SIZE, DEFAULT_REGION, DEFAULT_IMAGE
    )

    print(f"\nprobe droplet {droplet_id} — read markers with:")
    print(f"  aws s3 cp s3://{s3_bucket()}/{PROBE_KEY} -")
