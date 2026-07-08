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


def s3_bucket() -> str:
    """S3 bucket holding the fundamentals data repository.

    The AWS credentials themselves (``AWS_ACCESS_KEY_ID`` etc.) use botocore's
    standard names, so boto3/s3fs pick them up from the environment once
    ``load_dotenv`` has run — only the bucket name needs an accessor.
    """
    return _require("S3_BUCKET")


def is_paper() -> bool:
    return alpaca_config()["PAPER"]
