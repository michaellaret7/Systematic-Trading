"""Launch a self-destroying DigitalOcean droplet that runs the cloud smoke test.

Thin wrapper over ``systematic_trading.cloud.digitalocean.launch_job_droplet`` —
the droplet lifecycle (bootstrap, log shipping, self-delete) lives there. This
script only picks the job and its sizing.

Usage:
    uv run python scripts/launch_smoke_test.py
"""

from systematic_trading.cloud.digitalocean import launch_job_droplet

# The smoke test runs one agent with one tool, so it needs nothing like the
# 16 GB the trade-ideas fan-out does. s-1vcpu-2gb is DigitalOcean's cheapest
# size that still clears the ~1 GB the lumibot dependency tree imports into,
# and its 50 GB disk clears the 10 GB that overflowed on RunPod.
SIZE = "s-1vcpu-2gb"

if __name__ == "__main__":
    launch_job_droplet(
        job_name="smoke_test",
        job_module="systematic_trading.cloud.smoke_test",
        size=SIZE,
    )
