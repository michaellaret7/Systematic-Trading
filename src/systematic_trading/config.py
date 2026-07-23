"""Central configuration: loads secrets from the environment / .env file.

Nothing here is Lumibot-specific except ``alpaca_config()``, which returns the dict
shape Lumibot's ``Alpaca`` broker expects. Keep all credential handling in one place
so strategies and agents never read ``os.environ`` directly.
"""

from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

# Load .env from the project root once, on import. Real environment variables
# always win over .env values (override=False), which is what we want in CI/prod.
load_dotenv(override=False)

# The one CloudWatch Logs group the whole system streams to. The cloud bootstrap
# sets it as an env var on each pod, and the log reader defaults to it. Distinct
# from the ``CLOUDWATCH_LOG_GROUP`` env var read below: this is the canonical name;
# the env var is the runtime opt-in switch (absent -> stdout only).
CLOUDWATCH_LOG_GROUP = "systematic-trading"


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable {name!r}. "
            f"Copy .env.example to .env and fill it in."
        )
    return value


def alpaca_config() -> dict:
    """Return the broker config dict Lumibot's ``Alpaca`` class expects.

    ``PAPER`` defaults to True — live trading is opt-in via ``ALPACA_PAPER=false``.
    """
    return {
        "API_KEY": _require("ALPACA_API_KEY"),
        "API_SECRET": _require("ALPACA_API_SECRET"),
        "PAPER": os.getenv("ALPACA_PAPER", "true").lower() != "false",
    }


@lru_cache(maxsize=1)
def fmp_api_key() -> str:
    """Financial Modeling Prep API key, for data-enrichment calls inside strategies."""
    return _require("FMP_API_KEY")


def aws_region() -> str:
    """AWS region hosting the DynamoDB trade ledger (defaults to us-east-1).

    Uses botocore's standard variable name so the same setting steers every
    AWS SDK client; only DynamoDB needs it passed explicitly.
    """
    return os.getenv("AWS_DEFAULT_REGION", "us-east-1")


def s3_bucket() -> str:
    """S3 bucket holding the fundamentals data repository.

    The AWS credentials themselves (``AWS_ACCESS_KEY_ID`` etc.) use botocore's
    standard names, so boto3/s3fs pick them up from the environment once
    ``load_dotenv`` has run — only the bucket name needs an accessor.
    """
    return _require("S3_BUCKET")


def cloudwatch_config() -> dict[str, str] | None:
    """CloudWatch Logs target for the unified logger, or ``None`` when unset.

    Opt-in: returns ``None`` unless ``CLOUDWATCH_LOG_GROUP`` is present, so local
    runs stay stdout-only while cloud runs — which export it in the pod bootstrap —
    stream in real time. The stream name defaults to ``local`` for an ad-hoc run
    that sets only the group. AWS credentials and region use botocore's standard
    variables, already loaded by ``load_dotenv``.
    """
    group = os.getenv("CLOUDWATCH_LOG_GROUP")

    if not group:
        return None

    return {
        "log_group": group,
        "log_stream": os.getenv("CLOUDWATCH_LOG_STREAM", "local"),
        "region": aws_region(),
    }


def is_paper() -> bool:
    return alpaca_config()["PAPER"]
