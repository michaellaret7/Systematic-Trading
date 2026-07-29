"""Launch a DigitalOcean droplet that generates CSF Champions trade ideas.

The droplet clones the repo, runs the ``generate_trade_ideas`` workflow, syncs
its log to S3 / CloudWatch, and destroys itself when the job ends — so billing
stops on its own. This call returns in seconds; the run continues cloud-side.

    uv run python scripts/launch_ideas_droplet.py
"""

from systematic_trading.cloud.digitalocean import launch_job_droplet

JOB_NAME = "generate_trade_ideas"
JOB_MODULE = "systematic_trading.strategies.csf_champions.workflows.generate_trade_ideas"


if __name__ == "__main__":
    launch_job_droplet(JOB_NAME, JOB_MODULE)
