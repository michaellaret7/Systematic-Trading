"""Concise, readable logging for live trading.

Two channels, so the console reads as a clear strategy narrative:

  * **Framework (lumibot)** — quieted to WARNING. All of Lumibot's per-bar INFO
    chatter (data fetches, internal trade-event bookkeeping, socket notices)
    disappears; genuine warnings and errors still surface. A short deny-list drops
    a couple of noisy, non-actionable startup warnings.

  * **Strategy (`systematic_trading`)** — our own logger with a compact
    ``HH:MM:SS | message`` format. This is where the strategy says what it is doing:
    data arriving, momentum scores, orders, fills.

Telemetry JSON is disabled separately via ``LUMIBOT_TELEMETRY=false`` (see .env).
"""

from __future__ import annotations

import io
import logging
import sys

# Non-actionable framework warnings we don't want cluttering the console.
NOISE_SUBSTRINGS: tuple[str, ...] = (
    "LUMIWEALTH_API_KEY not set",
    "Not sending an update to the cloud",
    "quantity is None",
    "LUMIBOT_TELEMETRY",
)

_LOGGER_NAME = "systematic_trading"
_configured = False


class _NoiseFilter(logging.Filter):
    """Reject framework records whose message contains a known-noise substring."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()

        return not any(noise in message for noise in NOISE_SUBSTRINGS)


class _CompactFormatter(logging.Formatter):
    """``HH:MM:SS | message`` — timestamps without the date or logger plumbing."""

    def __init__(self) -> None:
        super().__init__(fmt="%(asctime)s | %(message)s", datefmt="%H:%M:%S")


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """Quiet Lumibot, set up the app's concise logger, and return it.

    Idempotent — safe to call more than once. Call once at startup, after
    ``import lumibot`` (which configures the "lumibot" logger) and before
    ``trader.run_all()``.
    """
    global _configured

    # Force UTF-8 console output. On Windows the default cp1252 encoding chokes on
    # Lumibot's Unicode progress bar, which aborts backtests mid-run ("Could not
    # advance to next trading day: 'charmap' codec can't encode...").
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")

    # Framework channel: warnings/errors only, minus known noise.
    lumibot_logger = logging.getLogger("lumibot")
    lumibot_logger.setLevel(logging.WARNING)

    for handler in lumibot_logger.handlers:
        if not any(isinstance(existing, _NoiseFilter) for existing in handler.filters):
            handler.addFilter(_NoiseFilter())

    # Strategy channel: our own handler + compact format, printed once (no root echo).
    app_logger = logging.getLogger(_LOGGER_NAME)

    if not _configured:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_CompactFormatter())

        app_logger.addHandler(handler)
        app_logger.propagate = False
        _configured = True

    app_logger.setLevel(level)

    return app_logger


def get_logger(name: str) -> logging.Logger:
    """Return a child of the app logger. Call ``configure_logging()`` once first."""
    return logging.getLogger(_LOGGER_NAME).getChild(name)
