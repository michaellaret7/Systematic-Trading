"""Launch a self-terminating RunPod CPU pod that runs the trade-ideas job.

Thin wrapper over ``systematic_trading.cloud.runpod.launch_pod`` — the pod
lifecycle (restart guard, self-delete, memory monitor, S3 log sync) lives
there. This script only picks the job and its sizing.

Usage:
    uv run python scripts/launch_trade_ideas_pod.py
"""

from systematic_trading.cloud.runpod import launch_pod

# The original cpu3c/2 gave 4 GB, and every one of the 30 full runs on
# 2026-07-17 died at 5-17 minutes without completing a single ticker —
# right as ~28 concurrent agent contexts (7 workers x 3 subagents) grew
# past it. cpu3g/4 gives 16 GB and 40 GB of disk for $0.16/hr, a few
# dollars for a full run.

if __name__ == "__main__":
    launch_pod(
        job_name="trade_ideas",
        job_module="systematic_trading.strategies.csf_champions.workflows.generate_trade_ideas",
        cpu_flavor="cpu3g",
        vcpu_count=4,
        container_disk_gb=40,
    )
