"""Stream cloud run logs into parsed records you can filter and collect.

The read side of the log pipeline whose write side lives in this package:
``bootstrap.py`` pipes each run to ``s3://<bucket>/logs/<job>/<stamp>/full.log`` and
streams it to the ``CLOUDWATCH_LOG_GROUP`` group; this module reads either back.
Both backends emit the same unified line format
(``HH:MM:SS | LEVEL | source | message`` — see ``docs/infrastructure/logging.md``),
so one parser serves both.

Three entry points, one per way to read:

- ``read_s3_log`` — a pod's complete, permanent ``full.log`` from S3 (first line to last).
- ``read_cloudwatch_log`` — a finite CloudWatch window (recent history, ≤ retention).
- ``tail_cloudwatch_log`` — a live follow of CloudWatch as records arrive.

Everything is a generator: lines are pulled and parsed one at a time, so a
multi-gigabyte archive filters without loading into memory. Wrap in ``list(...)``
when you want a concrete list — e.g. every INFO record from one pod::

    from systematic_trading.cloud.logs import read_s3_log

    infos = list(read_s3_log("logs/live_csf_champions/2026-07-23T14Z/full.log", level="INFO"))
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from typing import NamedTuple

import boto3

from systematic_trading.config import CLOUDWATCH_LOG_GROUP, aws_region, s3_bucket

__all__ = ["LogEntry", "read_s3_log", "read_cloudwatch_log", "tail_cloudwatch_log"]

# A record opens with a wall-clock stamp; every other line continues the one above
# it (a wrapped message or a traceback). Straight from the logging.md parser rule.
_RECORD_START = re.compile(r"^\d\d:\d\d:\d\d \| ")

# Continuation lines are aligned under the message column with "<spaces>| "; strip
# that prefix to recover the original message text.
_CONTINUATION_INDENT = re.compile(r"^ *\| ?")

_FIELD_SEP = " | "


class LogEntry(NamedTuple):
    """One parsed record. ``message`` keeps embedded newlines for multi-line records."""

    time: str
    level: str
    source: str
    message: str


#     ================================
# --> Helper funcs
#     ================================


def _parse_first_line(line: str) -> LogEntry:
    """Split a record's opening line on ``" | "`` — message keeps any later pipes."""
    time, level, source, message = line.split(_FIELD_SEP, 3)

    return LogEntry(time=time, level=level.strip(), source=source.strip(), message=message)


def _filtered(records: Iterator[LogEntry], level: str | None) -> Iterator[LogEntry]:
    """Yield records at ``level`` (case-insensitive), or all of them when ``level`` is None."""
    if level is None:
        yield from records
        return

    wanted = level.upper()

    for record in records:
        if record.level == wanted:
            yield record


def _log_group_arn(group: str) -> str:
    """Build the log-group ARN that Live Tail requires from the bare group name.

    ``start_live_tail`` identifies groups by ARN, not name, so the account id is
    looked up once via STS. Pass ``log_group_arn`` to ``tail_cloudwatch_log`` to skip this.
    """
    region = aws_region()
    account = boto3.client("sts", region_name=region).get_caller_identity()["Account"]

    return f"arn:aws:logs:{region}:{account}:log-group:{group}"


#     ================================
# --> Parsing
#     ================================


def parse_records(lines: Iterable[str]) -> Iterator[LogEntry]:
    """Group raw log lines into records, folding continuation lines into the record above.

    A line starting with ``HH:MM:SS | `` opens a record; anything else is a wrapped
    message or traceback and joins the current record's ``message``. Each record is
    yielded once the next one begins (and the last at end of stream). Lines before the
    first record (lumibot's banner, bootstrap output) are dropped.
    """
    current: LogEntry | None = None

    for raw in lines:
        line = raw.rstrip("\n")

        if _RECORD_START.match(line):
            if current is not None:
                yield current

            current = _parse_first_line(line)
            continue

        if current is None:
            continue

        continuation = _CONTINUATION_INDENT.sub("", line)

        current = current._replace(message=f"{current.message}\n{continuation}")

    if current is not None:
        yield current


#     ================================
# --> S3 source (complete pod history)
#     ================================


def s3_log_lines(key: str, bucket: str | None = None) -> Iterator[str]:
    """Stream one S3 log object line by line without loading it into memory.

    ``key`` is the object key, e.g. ``logs/live_csf_champions/<stamp>/full.log``;
    ``bucket`` defaults to the configured data bucket.
    """
    client = boto3.client("s3", region_name=aws_region())

    body = client.get_object(Bucket=bucket or s3_bucket(), Key=key)["Body"]

    for raw in body.iter_lines():
        yield raw.decode("utf-8", errors="replace")


def read_s3_log(
    key: str, *, level: str | None = None, bucket: str | None = None
) -> Iterator[LogEntry]:
    """Parsed records from an S3 log object, optionally filtered to one level.

    ``list(read_s3_log(key, level="INFO"))`` gives every INFO record from that pod.
    """
    return _filtered(parse_records(s3_log_lines(key, bucket)), level)


#     ================================
# --> CloudWatch source (windowed / live)
#     ================================


def cloudwatch_log_lines(
    group: str = CLOUDWATCH_LOG_GROUP,
    *,
    stream_prefix: str | None = None,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> Iterator[str]:
    """Stream CloudWatch events for a group as raw lines, paging lazily.

    ``stream_prefix`` narrows to one pod (e.g. ``live_csf_champions``); ``start_ms`` /
    ``end_ms`` bound the window in epoch milliseconds. An event message may hold a
    multi-line record, so it is split back into lines for the parser.
    """
    client = boto3.client("logs", region_name=aws_region())

    kwargs: dict[str, str | int] = {"logGroupName": group}

    if stream_prefix is not None:
        kwargs["logStreamNamePrefix"] = stream_prefix
    if start_ms is not None:
        kwargs["startTime"] = start_ms
    if end_ms is not None:
        kwargs["endTime"] = end_ms

    paginator = client.get_paginator("filter_log_events")

    for page in paginator.paginate(**kwargs):
        for event in page["events"]:
            yield from event["message"].splitlines()


def read_cloudwatch_log(
    group: str = CLOUDWATCH_LOG_GROUP,
    *,
    level: str | None = None,
    stream_prefix: str | None = None,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> Iterator[LogEntry]:
    """Parsed records from CloudWatch over a finite window, optionally filtered to one level."""
    lines = cloudwatch_log_lines(
        group, stream_prefix=stream_prefix, start_ms=start_ms, end_ms=end_ms
    )

    return _filtered(parse_records(lines), level)


def tail_cloudwatch_log(
    group: str = CLOUDWATCH_LOG_GROUP,
    *,
    level: str | None = None,
    stream_prefix: str | None = None,
    log_group_arn: str | None = None,
) -> Iterator[LogEntry]:
    """Yield records live as they land in CloudWatch — the real-time follow.

    Opens a Live Tail session and blocks between events, so iterating this generator
    tails the group indefinitely (until you stop, or AWS ends the session — Live Tail
    sessions time out on inactivity and cap total duration). Unlike ``read_*``, each
    delivered event is already one complete record, so it parses on arrival with no
    hold-for-next-line latency. Live Tail is a billed feature — don't leave one running
    unattended.

    ``stream_prefix`` narrows to one pod; ``level`` keeps only that level;
    ``log_group_arn`` overrides the STS-derived ARN.
    """
    client = boto3.client("logs", region_name=aws_region())

    arn = log_group_arn or _log_group_arn(group)

    kwargs: dict[str, list[str]] = {"logGroupIdentifiers": [arn]}

    if stream_prefix is not None:
        kwargs["logStreamNamePrefixes"] = [stream_prefix]

    response = client.start_live_tail(**kwargs)

    for event in response["responseStream"]:
        update = event.get("sessionUpdate")

        if update is None:
            continue

        for result in update["sessionResults"]:
            yield from _filtered(parse_records(result["message"].splitlines()), level)
