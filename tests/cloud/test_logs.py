"""Parsing and filtering for the cloud log reader.

Exercises the full parse flow on real-format log lines (the exact
``HH:MM:SS | LEVEL | source | message`` shape the unified logger emits), covering
the cases that matter: multi-line records folding a traceback into one entry, level
filtering, padded columns, embedded pipes in a message, and pre-log noise. No
network, no S3, no CloudWatch — the S3/CloudWatch sources are thin boto3 wrappers
around this parser.
"""

from systematic_trading.cloud.logs import LogEntry, parse_records
from systematic_trading.cloud.logs import _filtered  # noqa: PLC2701 — testing the filter directly

#     ================================
# --> Helper funcs
#     ================================

# A realistic slice: an ERROR record carries a two-line traceback continuation, and
# one INFO message contains an embedded " | " pipe to prove the split is bounded.
SAMPLE = [
    "Lumibot banner line before any record — must be dropped",
    "15:46:30 | INFO     | analyst_LVS          | tool.start GetFundamentalStatement()",
    "15:47:13 | INFO     | enter_positions      | LVS: buy 164 @ limit $45.29 | target 2.10%",
    "15:47:13 | ERROR    | ticker_analyst_MSFT  | tool.end GetFundamentals error: 404",
    "                                           | Traceback (most recent call last):",
    "                                           |   ValueError: unknown symbol",
    "15:47:44 | WARNING  | enter_positions      | MSFT: no price available — skipping entry",
]


#     ================================
# --> Tests
#     ================================


def test_parse_groups_continuations_and_drops_pre_log_noise():
    records = list(parse_records(SAMPLE))

    # 7 lines -> 4 records: the banner is dropped, the traceback folds into the ERROR.
    assert len(records) == 4
    assert [r.level for r in records] == ["INFO", "INFO", "ERROR", "WARNING"]


def test_columns_are_stripped_of_padding():
    first = next(parse_records(SAMPLE))

    assert first == LogEntry(
        time="15:46:30",
        level="INFO",
        source="analyst_LVS",
        message="tool.start GetFundamentalStatement()",
    )


def test_embedded_pipe_survives_in_message():
    records = list(parse_records(SAMPLE))
    buy = records[1]

    assert buy.source == "enter_positions"
    assert buy.message == "LVS: buy 164 @ limit $45.29 | target 2.10%"


def test_traceback_folds_into_one_record():
    error = list(parse_records(SAMPLE))[2]

    assert error.level == "ERROR"
    assert error.source == "ticker_analyst_MSFT"
    assert error.message.splitlines() == [
        "tool.end GetFundamentals error: 404",
        "Traceback (most recent call last):",
        "  ValueError: unknown symbol",
    ]


def test_level_filter_keeps_only_matches_case_insensitive():
    infos = list(_filtered(parse_records(SAMPLE), "info"))

    assert [r.source for r in infos] == ["analyst_LVS", "enter_positions"]
    assert all(r.level == "INFO" for r in infos)


def test_no_level_filter_passes_everything_through():
    assert len(list(_filtered(parse_records(SAMPLE), None))) == 4
