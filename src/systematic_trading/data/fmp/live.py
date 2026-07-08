"""Financial Modeling Prep stable-API client.

Wraps https://financialmodelingprep.com/stable/ for the two dataset families we use:

- **Historical prices** — every increment FMP offers: intraday bars (1min, 5min,
  15min, 30min, 1hour, 4hour) and daily EOD in three adjustment flavors. FMP caps
  how much each request returns (intraday windows span a few days to a few months
  depending on interval; daily is 5,000 rows) with no cursor, so the fetchers walk
  the requested range backward in windows and stitch the results.
- **Fundamentals** — income statement, balance sheet, cash flow statement, ratios.

Point-in-time note: statement rows carry ``acceptedDate`` (the SEC acceptance
timestamp — when the numbers became publicly known). Filter on it, never on
``date`` (the fiscal period end), when backtesting. Ratios carry no filing
timestamps; derive availability from the matching statement's ``acceptedDate``.
"""

import datetime as dt

import pandas as pd
import requests

from systematic_trading.config import fmp_api_key

FMP_BASE_URL = "https://financialmodelingprep.com/stable"
EASTERN_TZ = "America/New_York"

INTRADAY_INTERVALS = ("1min", "5min", "15min", "30min", "1hour", "4hour")

# Daily EOD endpoint per adjustment flavor. "split" matches how most backtests want
# prices; "dividend" is a total-return series; "none" is raw as-traded.
DAILY_ENDPOINTS = {
    "split": "historical-price-eod/full",
    "dividend": "historical-price-eod/dividend-adjusted",
    "none": "historical-price-eod/non-split-adjusted",
}

STATEMENT_PERIODS = frozenset({"annual", "quarter", "FY", "Q1", "Q2", "Q3", "Q4"})

PRICE_COLUMNS = ["open", "high", "low", "close", "volume"]

# The adjusted daily variants rename OHLC; map back so every price frame is uniform.
ADJUSTED_RENAMES = {"adjOpen": "open", "adjHigh": "high", "adjLow": "low", "adjClose": "close"}

STATEMENT_DATE_COLUMNS = ("date", "filingDate", "acceptedDate")


#     ================================
# --> Helper funcs
#     ================================


def _to_date(value: dt.date | dt.datetime | str) -> dt.date:
    """Coerce the mixed date inputs we accept into a plain ``date``."""
    if isinstance(value, dt.datetime):
        return value.date()

    if isinstance(value, dt.date):
        return value

    return dt.date.fromisoformat(value)


def _empty_price_frame() -> pd.DataFrame:
    """OHLCV frame with zero rows, so empty results still have the uniform shape."""
    index = pd.DatetimeIndex([], tz=EASTERN_TZ, name="date")

    return pd.DataFrame(columns=PRICE_COLUMNS, index=index)


def _price_frame(rows: list[dict]) -> pd.DataFrame:
    """Newest-first FMP price rows -> ascending OHLCV frame on an Eastern tz index.

    FMP stamps bars in exchange-local (US/Eastern) naive time; the index is
    localized accordingly. Window overlap from pagination is deduplicated here.
    """
    if not rows:
        return _empty_price_frame()

    df = pd.DataFrame(rows).rename(columns=ADJUSTED_RENAMES)

    index = pd.DatetimeIndex(pd.to_datetime(df["date"]), name="date").tz_localize(EASTERN_TZ)
    df = df.set_index(index)[PRICE_COLUMNS].apply(pd.to_numeric)

    df = df[~df.index.duplicated(keep="first")].sort_index()

    return df


def _statement_frame(rows: list[dict]) -> pd.DataFrame:
    """Newest-first FMP statement rows -> ascending frame with parsed date columns."""
    df = pd.DataFrame(rows)

    for column in STATEMENT_DATE_COLUMNS:
        if column in df.columns:
            df[column] = pd.to_datetime(df[column])

    if "date" in df.columns:
        df = df.sort_values("date", ignore_index=True)

    return df


#     ================================
# --> Client
#     ================================


class FMPClient:
    """Thin synchronous client for the FMP stable API.

    All methods return pandas DataFrames. Price frames are indexed by tz-aware
    Eastern timestamps with uniform ``open/high/low/close/volume`` columns;
    statement frames keep every field FMP returns, oldest row first.
    """

    def __init__(self, api_key: str | None = None, timeout: float = 30.0):
        self._api_key = api_key or fmp_api_key()
        self._timeout = timeout
        self._session = requests.Session()

    def _get(self, path: str, params: dict) -> list[dict]:
        """One GET against the stable API; raises on HTTP or FMP-level errors."""
        response = self._session.get(
            f"{FMP_BASE_URL}/{path}",
            params={**params, "apikey": self._api_key},
            timeout=self._timeout,
        )

        if not response.ok:
            raise RuntimeError(f"FMP {path} failed ({response.status_code}): {response.text[:300]}")

        payload = response.json()

        # FMP signals plan/param errors as a JSON object, not a list of rows.
        if isinstance(payload, dict):
            raise RuntimeError(f"FMP {path} returned an error: {payload}")

        return payload

    def _paged_price_rows(self, path: str, symbol: str, start: dt.date, end: dt.date) -> list[dict]:
        """Walk ``[start, end]`` backward in windows until the range is covered.

        FMP anchors each response at ``to`` and returns only the newest slice of
        the range, with no cursor. Re-anchoring ``to`` at the oldest day received
        walks arbitrarily far back; the overlap is deduplicated in `_price_frame`.
        """
        rows: list[dict] = []
        window_end = end

        while window_end >= start:
            page = self._get(
                path,
                {"symbol": symbol, "from": start.isoformat(), "to": window_end.isoformat()},
            )

            if not page:
                break

            rows.extend(page)

            oldest = _to_date(min(row["date"] for row in page)[:10])

            if oldest <= start:
                break

            # Step a full day back instead if re-anchoring would not make progress.
            window_end = oldest if oldest < window_end else window_end - dt.timedelta(days=1)

        return rows

    def _statements(self, path: str, symbol: str, period: str, limit: int) -> pd.DataFrame:
        """Shared fetch for the statement-shaped endpoints."""
        if period not in STATEMENT_PERIODS:
            raise ValueError(
                f"Unknown period {period!r}; expected one of {sorted(STATEMENT_PERIODS)}."
            )

        rows = self._get(path, {"symbol": symbol, "period": period, "limit": limit})

        return _statement_frame(rows)

    def intraday_prices(
        self,
        symbol: str,
        interval: str,
        start: dt.date | dt.datetime | str,
        end: dt.date | dt.datetime | str,
    ) -> pd.DataFrame:
        """Intraday OHLCV bars (split-adjusted). ``interval`` is one of INTRADAY_INTERVALS."""
        if interval not in INTRADAY_INTERVALS:
            raise ValueError(
                f"Unknown interval {interval!r}; expected one of {INTRADAY_INTERVALS}."
            )

        rows = self._paged_price_rows(
            f"historical-chart/{interval}", symbol, _to_date(start), _to_date(end)
        )

        return _price_frame(rows)

    def daily_prices(
        self,
        symbol: str,
        start: dt.date | dt.datetime | str,
        end: dt.date | dt.datetime | str,
        adjustment: str = "split",
    ) -> pd.DataFrame:
        """Daily EOD OHLCV bars. ``adjustment`` is 'split', 'dividend', or 'none'."""
        if adjustment not in DAILY_ENDPOINTS:
            raise ValueError(
                f"Unknown adjustment {adjustment!r}; expected one of {sorted(DAILY_ENDPOINTS)}."
            )

        rows = self._paged_price_rows(
            DAILY_ENDPOINTS[adjustment], symbol, _to_date(start), _to_date(end)
        )

        return _price_frame(rows)

    def screener(
        self,
        market_cap_more_than: float | None = None,
        price_more_than: float | None = None,
        exchange: str | None = None,
        limit: int = 5000,
    ) -> pd.DataFrame:
        """Company screener; one row per matching stock (symbol, marketCap, price, ...).

        ``exchange`` is comma-separated, e.g. ``"NASDAQ,NYSE,AMEX"``. ETFs, funds,
        and inactive listings are always excluded — this feeds a fundamental stock
        screener, so only tradable common stocks belong in the universe.
        """
        params: dict = {
            "isEtf": "false",
            "isFund": "false",
            "isActivelyTrading": "true",
            "limit": limit,
        }

        if market_cap_more_than is not None:
            params["marketCapMoreThan"] = int(market_cap_more_than)

        if price_more_than is not None:
            params["priceMoreThan"] = price_more_than

        if exchange is not None:
            params["exchange"] = exchange

        rows = self._get("company-screener", params)

        return pd.DataFrame(rows)

    def income_statement(
        self, symbol: str, period: str = "annual", limit: int = 40
    ) -> pd.DataFrame:
        """Income statements, oldest first. ``acceptedDate`` marks public availability."""
        return self._statements("income-statement", symbol, period, limit)

    def balance_sheet(self, symbol: str, period: str = "annual", limit: int = 40) -> pd.DataFrame:
        """Balance sheets, oldest first. ``acceptedDate`` marks public availability."""
        return self._statements("balance-sheet-statement", symbol, period, limit)

    def cash_flow(self, symbol: str, period: str = "annual", limit: int = 40) -> pd.DataFrame:
        """Cash flow statements, oldest first. ``acceptedDate`` marks public availability."""
        return self._statements("cash-flow-statement", symbol, period, limit)

    def ratios(self, symbol: str, period: str = "annual", limit: int = 40) -> pd.DataFrame:
        """Financial ratios, oldest first.

        Ratios rows have NO ``filingDate``/``acceptedDate`` — for point-in-time
        joins, gate on the matching statement's ``acceptedDate`` instead.
        """
        return self._statements("ratios", symbol, period, limit)

    def key_metrics(self, symbol: str, period: str = "annual", limit: int = 40) -> pd.DataFrame:
        """Key metrics (per-share values, returns, yields), oldest first.

        Like ratios, rows carry no filing timestamps; for point-in-time joins,
        gate on the matching statement's ``acceptedDate`` instead.
        """
        return self._statements("key-metrics", symbol, period, limit)
