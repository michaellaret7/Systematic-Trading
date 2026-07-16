"""Universe exclusions and symbol-pruning behavior."""

import pandas as pd

from systematic_trading.data.universe import (
    EXCHANGE_TRADED_DEBT,
    EXCLUDED_SYMBOLS,
    OTHER_NON_COMMON_SECURITIES,
    PREFERRED_SECURITIES,
    UNVERIFIED_LISTINGS,
    drop_symbols,
)


def test_drop_symbols_removes_only_requested_rows():
    frame = pd.DataFrame(
        {
            "symbol": ["KEEP", "DUKB", "KEEP", "SOJC"],
            "value": [1, 2, 3, 4],
        }
    )

    cleaned, removed = drop_symbols(frame, {"DUKB", "SOJC"})

    assert removed == 2
    assert cleaned["symbol"].tolist() == ["KEEP", "KEEP"]
    assert cleaned["value"].tolist() == [1, 3]


def test_drop_symbols_is_idempotent():
    frame = pd.DataFrame({"symbol": ["KEEP"], "value": [1]})

    cleaned, removed = drop_symbols(frame, {"DUKB"})

    assert removed == 0
    pd.testing.assert_frame_equal(cleaned, frame)


def test_audited_exclusions_cover_distinct_instrument_categories():
    categories = (
        EXCHANGE_TRADED_DEBT,
        PREFERRED_SECURITIES,
        OTHER_NON_COMMON_SECURITIES,
        UNVERIFIED_LISTINGS,
    )

    assert EXCLUDED_SYMBOLS == frozenset().union(*categories)
    assert sum(map(len, categories)) == len(EXCLUDED_SYMBOLS)
    assert {"FGN", "SOJC", "STRF", "CCXIW", "HONAV"} <= EXCLUDED_SYMBOLS
    assert "TRMD" not in EXCLUDED_SYMBOLS
