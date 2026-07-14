"""Explicit universe exclusions for instruments misclassified as common stocks.

Reviewed against Nasdaq Trader's ``nasdaqlisted.txt`` and ``otherlisted.txt``
security descriptions on 2026-07-13. FMP attaches issuer fundamentals and
market capitalization to these subordinate instruments as if they were stock.
"""

import pandas as pd

EXCHANGE_TRADED_DEBT = frozenset(
    {
        "ABXL",
        "AEFC",
        "AIZN",
        "APOS",
        "AQNB",
        "ASBA",
        "ATHS",
        "BEPH",
        "BEPI",
        "BIPH",
        "BIPI",
        "BNH",
        "BNJ",
        "CCZ",
        "CGABL",
        "CMSA",
        "CMSC",
        "CMSD",
        "DTB",
        "DTG",
        "DTW",
        "DUKB",
        "ELC",
        "ELLA",
        "FGN",
        "HCXY",
        "JSM",
        "KKRS",
        "MGR",
        "MGRB",
        "MGRD",
        "MGRE",
        "OXLCG",
        "PFH",
        "PFLA",
        "PRH",
        "PRS",
        "RWTN",
        "RWTQ",
        "RZC",
        "SOJC",
        "SOJD",
        "SOJE",
        "SREA",
        "TBB",
        "TCPA",
        "UNMA",
        "UZD",
        "UZE",
        "UZF",
        "XELLL",
    }
)

PREFERRED_SECURITIES = frozenset(
    {
        "BMNP",
        "BPYPO",
        "CIB",
        "FCNCN",
        "ITUB",
        "LILAP",
        "OAK-PA",
        "OAK-PB",
        "PBR-A",
        "SATA",
        "SEAL-PB",
        "STRC",
        "STRD",
        "STRF",
        "STRK",
        "TRTN-PC",
    }
)

OTHER_NON_COMMON_SECURITIES = frozenset(
    {
        "ARCC",  # closed-end investment company
        "CCXIW",  # warrant
        "GBDC",  # closed-end investment company
        "NOVTU",  # tangible equity units
        "PPLC",  # corporate units
        "SOMN",  # corporate units
    }
)

# Current FMP candidates absent from the official US listed-security directories.
# This includes stale provider aliases, preferred syntax mismatches, and temporary
# when-issued/distribution symbols. Preferred mismatches are classified above.
UNVERIFIED_LISTINGS = frozenset(
    {
        "HONAV",
        "IAC",
        "LILKV",
        "MIDDV",
        "SATS",
        "SKHYV",
        "VSCO",
    }
)

EXCLUDED_INSTRUMENTS: dict[str, str] = {
    **{symbol: "exchange-traded debt" for symbol in EXCHANGE_TRADED_DEBT},
    **{symbol: "preferred security" for symbol in PREFERRED_SECURITIES},
    **{symbol: "non-common security" for symbol in OTHER_NON_COMMON_SECURITIES},
    **{symbol: "not in official US listed-security directories" for symbol in UNVERIFIED_LISTINGS},
}

EXCLUDED_SYMBOLS = frozenset(EXCLUDED_INSTRUMENTS)


def drop_symbols(frame: pd.DataFrame, symbols: set[str]) -> tuple[pd.DataFrame, int]:
    """Return the frame without target symbols and the number of removed rows."""
    remove = frame["symbol"].isin(symbols)

    return frame.loc[~remove].copy(), int(remove.sum())
