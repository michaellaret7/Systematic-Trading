from __future__ import annotations

import pandas as pd

from systematic_trading.screeners.csf_champions import build_panel, screen


PASSING_METRICS = {
    "roic_ttm": 0.20,
    "roic_floor_5y": 0.12,
    "fcf_margin_ttm": 0.12,
    "income_quality_ttm": 1.2,
    "fcf_positive_quarters_5y": 20,
    "accruals_ratio_ttm": 0.02,
    "dso_change_3y": 5.0,
    "sbc_to_revenue_ttm": 0.03,
    "net_debt_to_ebitda": 0.5,
    "interest_coverage": 20.0,
    "revenue_cagr_5y": 0.08,
    "revenue_growth_years_5y": 5,
    "fcf_ps_cagr_5y": 0.09,
    "share_change_3y": 0.01,
    "incremental_roic_5y": 0.18,
    "gross_margin_std_5y": 0.03,
    "gross_profitability_ttm": 0.40,
    "payout_to_fcf_5y": 0.60,
}


def panel_row(
    symbol: str,
    date: str,
    available_from: str,
    **overrides: float,
) -> dict[str, object]:
    row: dict[str, object] = {
        "symbol": symbol,
        "date": pd.Timestamp(date),
        "available_from": pd.Timestamp(available_from),
    }
    row.update(PASSING_METRICS)
    row.update(overrides)

    return row


def statement_frame(
    dates: pd.DatetimeIndex,
    accepted_offset_days: int,
    values: dict[str, float],
) -> pd.DataFrame:
    rows = []

    for index, date in enumerate(dates):
        row = {
            "symbol": "AAA",
            "date": date,
            "acceptedDate": date + pd.Timedelta(days=accepted_offset_days),
        }
        row.update({column: value + index for column, value in values.items()})
        rows.append(row)

    return pd.DataFrame(rows)


def test_screen_uses_latest_visible_row_without_lookahead() -> None:
    panel = pd.DataFrame(
        [
            panel_row("AAA", "2023-12-31", "2024-02-15", roic_ttm=0.18),
            panel_row("AAA", "2024-03-31", "2024-05-15", roic_ttm=0.30),
            panel_row("BBB", "2023-12-31", "2024-02-20", roic_ttm=0.22),
        ]
    )

    champions = screen(panel, as_of="2024-03-31")

    assert set(champions["symbol"]) == {"AAA", "BBB"}
    assert champions.loc[champions["symbol"] == "AAA", "roic_ttm"].item() == 0.18


def test_screen_drops_stale_symbols() -> None:
    panel = pd.DataFrame(
        [
            panel_row("FRESH", "2024-03-31", "2024-05-01"),
            panel_row("STALE", "2022-12-31", "2023-02-15"),
        ]
    )

    champions = screen(panel, as_of="2024-06-30")

    assert champions["symbol"].tolist() == ["FRESH"]


def test_screen_applies_criteria_overrides() -> None:
    panel = pd.DataFrame([panel_row("AAA", "2024-03-31", "2024-05-01", roic_ttm=0.20)])

    champions = screen(panel, as_of="2024-06-30", criteria={"roic_ttm_min": 0.25})

    assert champions.empty


def test_build_panel_marks_rows_available_after_all_statements_arrive() -> None:
    dates = pd.date_range("2018-03-31", periods=24, freq="QE")
    income = statement_frame(
        dates,
        30,
        {
            "revenue": 100.0,
            "grossProfit": 60.0,
            "ebit": 30.0,
            "interestExpense": 1.0,
            "incomeTaxExpense": 5.0,
            "incomeBeforeTax": 25.0,
            "netIncome": 20.0,
            "weightedAverageShsOutDil": 10.0,
        },
    )
    balance = statement_frame(
        dates,
        35,
        {
            "totalAssets": 300.0,
            "totalDebt": 20.0,
            "netDebt": 5.0,
            "totalEquity": 180.0,
            "cashAndShortTermInvestments": 15.0,
            "netReceivables": 25.0,
        },
    )
    cashflow = statement_frame(
        dates,
        40,
        {
            "operatingCashFlow": 28.0,
            "capitalExpenditure": -5.0,
            "freeCashFlow": 23.0,
            "acquisitionsNet": -1.0,
            "stockBasedCompensation": 1.0,
            "depreciationAndAmortization": 3.0,
            "netDividendsPaid": -8.0,
            "netStockIssuance": -2.0,
        },
    )
    key_metrics = statement_frame(
        dates,
        0,
        {
            "marketCap": 1000.0,
            "enterpriseValue": 1005.0,
        },
    ).drop(columns="acceptedDate")

    panel = build_panel(income, balance, cashflow, key_metrics)

    assert panel.loc[0, "available_from"] == dates[0] + pd.Timedelta(days=40)
    assert {"symbol", "date", "available_from", "roic_ttm", "revenue_cagr_5y"}.issubset(
        panel.columns
    )
    assert len(panel) == len(dates)
