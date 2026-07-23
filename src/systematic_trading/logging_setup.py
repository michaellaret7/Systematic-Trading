"""One log line format for the whole system, regardless of which subsystem emitted it.

A live run produces four independent logger trees — our own ``systematic_trading``,
Lumibot's ``lumibot``, ``agent_harness``'s ``agent`` sink loggers, and ``agent_harness``'s
own diagnostics. Each ships a different format. This module unifies them behind a single
handler on the **root** logger, so everything that propagates up renders as:

    HH:MM:SS | LEVEL    | source               | message

See ``docs/infrastructure/logging.md`` for the full design and the third-party quirks it
works around (Lumibot re-configuring its logger on every call, ``agent_harness``
bootstrapping its own handler, and why the noise filter must live on a handler).

Call ``configure_logging()`` once at startup, after ``import lumibot`` and before the
first ``LogSink`` is constructed. It is idempotent.
"""

from __future__ import annotations

import atexit
import io
import logging
import sys

from systematic_trading.config import cloudwatch_config

# Non-actionable framework warnings we don't want cluttering the console.
NOISE_SUBSTRINGS: tuple[str, ...] = (
    "LUMIWEALTH_API_KEY not set",
    "Not sending an update to the cloud",
    "quantity is None",
    "LUMIBOT_TELEMETRY",
)

# Trailing logger-name segments that are too generic to identify a source on their own;
# the segment before them is used instead (``...csf_champions.strategy`` -> ``csf_champions``,
# ``...risk_manager.agent`` -> ``risk_manager``).
_GENERIC_SEGMENTS: frozenset[str] = frozenset({"strategy", "agent"})

_LOGGER_NAME = "systematic_trading"
_LEVEL_WIDTH = 8
_SOURCE_WIDTH = 20

# CloudWatch keeps the real-time + recent window; S3 is the permanent archive.
_CLOUDWATCH_RETENTION_DAYS = 90

# How often watchtower ships batched records to CloudWatch (seconds) — the delay
# before a log line becomes visible to `aws logs tail` / `tail_cloudwatch_log`.
# Lower = snappier real-time at the cost of more PutLogEvents calls; 60 is
# watchtower's own default. A batch also flushes early when it fills.
_CLOUDWATCH_SEND_INTERVAL_SECONDS = 30

# Lumibot logs "Processing trade event ..." at INFO right before the "New order was
# created"/"Order was filled" line that carries the same info with more detail. We can't
# lower it at the source (Lumibot hard-codes INFO), so it is treated as a debug-only line:
# hidden unless the app runs at DEBUG. Flipped by ``configure_logging``.
_show_broker_plumbing = False

_configured = False
_cloudwatch_attached = False


#     ================================
# --> Helper funcs
#     ================================


def _source(name: str) -> str:
    """Derive the source column from a logger name: its last meaningful segment.

    The last dotted segment names the source, except when it is too generic to mean
    anything (``strategy``, ``agent``), in which case the segment before it is used.
    """
    segments = name.split(".")

    # Agent sinks all live under the `agent.` tree; tag them `<name>_agent` so an agent
    # line is obvious at a glance (`agent.constructor` -> `constructor_agent`). The full
    # remainder is used, not the last segment, so dotted tickers survive (`BRK.B`).
    if segments[0] == "agent" and len(segments) >= 2:
        return f"{name[len('agent.') :]}_agent"

    last = segments[-1]

    if last in _GENERIC_SEGMENTS and len(segments) >= 2:
        return segments[-2]

    # Strip the private-module underscore some framework modules carry
    # (`lumibot.strategies._strategy` -> `strategy`).
    return last.lstrip("_")


class _NoiseFilter(logging.Filter):
    """Reject records whose message contains a known-noise substring.

    Lives on our root handler, not on a logger: a logger's filters run only for records
    logged directly on it, and every noise message originates on a Lumibot *child* logger.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()

        return not any(noise in message for noise in NOISE_SUBSTRINGS)


class _BrokerPlumbingFilter(logging.Filter):
    """Drop Lumibot's redundant "Processing trade event" line unless running at DEBUG.

    The line duplicates the "New order was created"/"Order was filled" record that follows
    it. Lumibot hard-codes it at INFO, so it can't be lowered at the source; this filter
    hides it by default and lets it through when ``_show_broker_plumbing`` is set (DEBUG),
    making it effectively a debug-only line without silencing the rest of the broker channel.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if _show_broker_plumbing:
            return True

        return "Processing trade event" not in record.getMessage()


class _ExcludeAwsChatter(logging.Filter):
    """Drop AWS-SDK records so the CloudWatch handler can't feed back into itself.

    Watchtower ships log events over botocore/urllib3, which log through the root
    logger too. On the CloudWatch handler their records would trigger more shipping
    calls — an amplifying loop. Root sits at WARNING so most never fire, but a
    single retry WARNING is enough, so this filter lives on the CloudWatch handler
    only (the console still shows a genuine boto warning).
    """

    _PREFIXES = ("botocore", "boto3", "urllib3", "s3transfer", "watchtower")

    def filter(self, record: logging.LogRecord) -> bool:
        return not record.name.startswith(self._PREFIXES)


class _RejectAll(logging.Filter):
    """Silence a handler without removing it — used to mute Lumibot's own console handler.

    Lumibot re-adds a console handler whenever its handler list is empty, so the handler
    cannot be deleted. Rejecting every record here lets Lumibot's logs propagate to the
    root handler instead of printing twice; Lumibot never touches ``handler.filters``.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return False


class _UnifiedFormatter(logging.Formatter):
    """The single definition of a log line. Multi-line messages indent to the message column."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = self.formatTime(record, "%H:%M:%S")
        source = _source(record.name)

        prefix = f"{timestamp} | {record.levelname:<{_LEVEL_WIDTH}} | {source:<{_SOURCE_WIDTH}.{_SOURCE_WIDTH}} | "

        message = record.getMessage().strip()
        lines = message.split("\n")

        first = prefix + lines[0]

        if len(lines) == 1:
            return first

        # Continuation lines align under the message column: spaces up to the final
        # "| " so the pipe stacks vertically and the table stays readable.
        indent = " " * (len(prefix) - 2) + "| "

        return "\n".join([first] + [indent + line for line in lines[1:]])


def _mute_lumibot_handlers() -> None:
    """Attach a reject-all filter to Lumibot's console handler(s) so records propagate to root."""
    lumibot_logger = logging.getLogger("lumibot")

    for handler in lumibot_logger.handlers:
        if not any(isinstance(existing, _RejectAll) for existing in handler.filters):
            handler.addFilter(_RejectAll())


def _repair_agent_tree(level: int) -> None:
    """Undo any ``LogSink`` bootstrap so agent records propagate to root under our format.

    ``LogSink`` wires its own stderr handler and sets ``propagate = False`` if it is
    constructed before us. Clearing the handlers and restoring propagation makes ordering
    irrelevant: a root handler then satisfies ``hasHandlers()`` and future sinks defer.
    """
    agent_logger = logging.getLogger("agent")

    for handler in list(agent_logger.handlers):
        agent_logger.removeHandler(handler)

    agent_logger.setLevel(level)
    agent_logger.propagate = True


def _attach_cloudwatch() -> None:
    """Add a second root handler that streams every record to CloudWatch Logs.

    Opt-in and idempotent: does nothing unless ``cloudwatch_config()`` is set
    (cloud runs export it; local runs stay stdout-only). Reuses ``_UnifiedFormatter``
    so a CloudWatch line is byte-for-byte the console line, and carries the same
    noise/broker filters plus ``_ExcludeAwsChatter`` to break the shipping feedback
    loop. ``boto3`` and ``watchtower`` are imported lazily so the local and data
    paths never pay for them.

    Failure is swallowed to stdout-only: a logging handler must never take the
    strategy down, and a credentials or IAM gap should degrade, not crash.
    """
    global _cloudwatch_attached

    if _cloudwatch_attached:
        return

    config = cloudwatch_config()

    if config is None:
        return

    try:
        import boto3
        import watchtower

        client = boto3.client("logs", region_name=config["region"])

        # No ``log_group_retention_days`` here on purpose: watchtower sets retention
        # inside this constructor, where a denied ``logs:PutRetentionPolicy`` would
        # raise and disable streaming entirely. Retention is set separately below so
        # it can fail quietly. ``create_log_group`` still creates the group + stream,
        # which is all streaming needs.
        handler = watchtower.CloudWatchLogHandler(
            log_group_name=config["log_group"],
            log_stream_name=config["log_stream"],
            boto3_client=client,
            create_log_group=True,
            send_interval=_CLOUDWATCH_SEND_INTERVAL_SECONDS,
        )
    except Exception as error:
        logging.getLogger(_LOGGER_NAME).warning(
            "CloudWatch logging disabled — falling back to stdout only: %s", error
        )
        return

    handler.setFormatter(_UnifiedFormatter())
    handler.addFilter(_NoiseFilter())
    handler.addFilter(_BrokerPlumbingFilter())
    handler.addFilter(_ExcludeAwsChatter())

    logging.getLogger().addHandler(handler)

    # Flush the background queue before exit so the last events reach CloudWatch.
    atexit.register(handler.flush)

    # Best-effort retention: the group already exists (created above), so this just
    # sets its expiry. A missing ``logs:PutRetentionPolicy`` permission leaves the
    # group at its default and logs a debug line — streaming is already live.
    try:
        client.put_retention_policy(
            logGroupName=config["log_group"], retentionInDays=_CLOUDWATCH_RETENTION_DAYS
        )
    except Exception as error:
        logging.getLogger(_LOGGER_NAME).debug(
            "CloudWatch retention not set (streaming unaffected): %s", error
        )

    _cloudwatch_attached = True


#     ================================
# --> Public API
#     ================================


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """Install the unified root handler and return the app logger. Idempotent.

    Call once at startup, after ``import lumibot`` (whose first-time config would remove
    our handler) and before the first ``LogSink``. ``level`` sets the ``systematic_trading``
    and ``agent`` trees; the root stays at WARNING so unconfigured third-party loggers
    (httpx, botocore, ...) do not leak INFO.
    """
    global _configured, _show_broker_plumbing

    # Broker plumbing lines surface only when the app runs at DEBUG.
    _show_broker_plumbing = level <= logging.DEBUG

    # Force UTF-8 console output. On Windows the default cp1252 encoding chokes on
    # Lumibot's Unicode progress bar, which aborts backtests mid-run ("Could not
    # advance to next trading day: 'charmap' codec can't encode...").
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")

    root_logger = logging.getLogger()

    if not _configured:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_UnifiedFormatter())
        handler.addFilter(_NoiseFilter())
        handler.addFilter(_BrokerPlumbingFilter())

        root_logger.addHandler(handler)
        _configured = True

    # Root stays quiet so unconfigured loggers inherit WARNING; our trees opt into `level`.
    root_logger.setLevel(logging.WARNING)

    app_logger = logging.getLogger(_LOGGER_NAME)
    app_logger.setLevel(level)
    app_logger.propagate = True

    _repair_agent_tree(level)
    _mute_lumibot_handlers()
    _attach_cloudwatch()

    return app_logger


def get_logger(name: str) -> logging.Logger:
    """Return a child of the app logger. Call ``configure_logging()`` once first."""
    return logging.getLogger(_LOGGER_NAME).getChild(name)
