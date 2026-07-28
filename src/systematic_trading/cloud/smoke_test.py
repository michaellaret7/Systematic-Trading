"""Smallest job that exercises the whole cloud-job lifecycle end to end.

Deployed with ``launch_job_droplet`` to prove the machinery works before a real
job depends on it: the droplet boots, clones the repo, installs dependencies,
reaches S3 and OpenRouter, ships logs to both backends, and destroys itself.

The agent is deliberately trivial — one read-only tool, one question. What is
being tested is the plumbing around it, not the answer. Every phase is logged
with a ``SMOKE`` marker so a single filter tells you how far the run got::

    aws logs tail systematic-trading --log-stream-name-prefix smoke_test --follow
    aws logs filter-log-events --log-group-name systematic-trading --filter-pattern SMOKE

A run that reaches ``SMOKE 4/4`` proves the repo checkout, the S3 parquet read,
the OpenRouter call, and the log pipeline all work on a fresh machine.
"""

import socket

from agent_harness.agent import Agent
from agent_harness.sinks import LogSink

from systematic_trading.agents.shared_tools.prices import get_recent_prices
from systematic_trading.logging_setup import configure_logging, get_logger

log = get_logger(__name__)

MODEL = "openai/gpt-5.6-sol"

# One ticker with a long, dense history, so a missing bar means the S3 read
# genuinely failed rather than the symbol being thinly traded.
TICKER = "AAPL"

SYSTEM = (
    "You are a smoke test. Call GetRecentPrices for the ticker you are given and "
    "reply with exactly one sentence stating its latest close and the date of that "
    "close. Do not add commentary."
)


def run_smoke_test() -> str:
    """Run the four-phase smoke test; returns the agent's one-sentence answer.

    Raises whatever the underlying step raises — a failure should end the run
    loudly so the log shows which phase it died in.
    """
    log.info("SMOKE 1/4 | job started on %s", socket.gethostname())

    # Calling the tool directly first separates an S3/credentials failure from a
    # model failure: if this line dies, the agent never had a chance.
    preview = get_recent_prices(TICKER)

    log.info("SMOKE 2/4 | S3 price read OK — %d chars for %s", len(preview), TICKER)

    agent = Agent(
        provider="openrouter",
        model=MODEL,
        system=SYSTEM,
        tools=[get_recent_prices],
    )

    log.info("SMOKE 3/4 | agent built on %s — calling OpenRouter", MODEL)

    answer = agent.run(f"Report the latest close for {TICKER}.", sink=LogSink("smoke"))

    log.info("SMOKE 4/4 | agent replied: %s", answer.strip())
    log.info("SMOKE done | all phases passed — droplet will self-destruct")

    return answer


if __name__ == "__main__":
    configure_logging()
    run_smoke_test()
