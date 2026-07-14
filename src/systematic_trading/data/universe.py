"""Universe rules: explicit instrument exclusions and the USD/quarterly filter.

Explicit exclusions were reviewed against Nasdaq Trader's ``nasdaqlisted.txt``
and ``otherlisted.txt`` security descriptions on 2026-07-13. FMP attaches
issuer fundamentals and market capitalization to these subordinate instruments
as if they were stock.

``usd_quarterly_symbols`` is the data-layer rule keeping the fundamentals
repository to US-style filers: statements in USD at quarterly cadence.
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

# Median gap between recent fiscal period ends above this is not quarterly
# reporting (true quarters land ~91 days apart; semiannual filers land ~182).
QUARTERLY_MAX_MEDIAN_GAP_DAYS = 100


def drop_symbols(frame: pd.DataFrame, symbols: set[str]) -> tuple[pd.DataFrame, int]:
    """Return the frame without target symbols and the number of removed rows."""
    remove = frame["symbol"].isin(symbols)

    return frame.loc[~remove].copy(), int(remove.sum())


def usd_quarterly_symbols(income_quarter: pd.DataFrame) -> set[str]:
    """Symbols whose income (quarter) rows are USD-denominated at quarterly cadence.

    Foreign private issuers file statements in local currency and often only
    semiannually. Both break the math every consumer assumes: local-currency
    values against FMP's USD market caps corrupt yields/EV multiples, and
    six-month rows in the quarter files double TTM sums. A symbol is kept only
    when its latest ``reportedCurrency`` is USD and the median gap between its
    recent period-end dates looks quarterly. Symbols with fewer than two rows
    cannot prove their cadence and are dropped until more history accrues.

    Needs the ``symbol``, ``date`` and ``reportedCurrency`` columns.
    """
    keep: set[str] = set()

    for symbol, group in income_quarter.groupby("symbol"):
        rows = group.sort_values("date")

        if rows["reportedCurrency"].iloc[-1] != "USD":
            continue

        recent = rows["date"].tail(5)

        if len(recent) < 2:
            continue

        median_gap_days = float(recent.diff().dt.days.median())

        if median_gap_days > QUARTERLY_MAX_MEDIAN_GAP_DAYS:
            continue

        keep.add(str(symbol))

    return keep
