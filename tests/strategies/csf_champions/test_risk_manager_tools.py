"""CSF Champions risk-manager agent tools."""

import pandas as pd
import pytest
import yaml

from systematic_trading.strategies.csf_champions.agents.risk_manager import tools
from systematic_trading.strategies.csf_champions.screening import DISPLAY_COLUMNS

# ====================================
# --> Helper funcs
# ====================================


def _ranked_candidates() -> pd.DataFrame:
    """Return ranked candidates with the screener's display columns."""
    symbols = ["CHEAP", "VALUE", "QUALITY"]
    rows = []

    for rank, symbol in enumerate(symbols):
        row = {column: 1.0 - rank / 10 for column in DISPLAY_COLUMNS if column != "symbol"}
        row["symbol"] = symbol
        rows.append(row)

    return pd.DataFrame(rows, columns=DISPLAY_COLUMNS)


def test_run_screener_exposes_optional_exclusion_list() -> None:
    """The agent schema exposes ticker exclusions as an optional string list."""
    parameters = tools.run_screener.tool["parameters"]
    exclusion = parameters["properties"]["exclude_tickers"]

    assert exclusion["type"] == "array"
    assert exclusion["items"] == {"type": "string"}
    assert exclusion["default"] is None
    assert "exclude_tickers" not in parameters.get("required", [])


def test_run_screener_returns_top_n_without_exclusions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Omitting exclusions preserves the ranked screen order."""
    monkeypatch.setattr(tools, "screen", _ranked_candidates)

    payload = yaml.safe_load(tools.run_screener(top_n=2))

    assert payload["requested_exclusions"] == 0
    assert payload["excluded"] == 0
    assert [row["symbol"] for row in payload["candidates"]] == ["CHEAP", "VALUE"]


def test_run_screener_normalizes_and_excludes_before_top_n(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requested holdings are removed case-insensitively before truncation."""
    monkeypatch.setattr(tools, "screen", _ranked_candidates)

    payload = yaml.safe_load(
        tools.run_screener(top_n=2, exclude_tickers=[" cheap ", "CHEAP", "missing"])
    )

    assert payload["requested_exclusions"] == 2
    assert payload["excluded"] == 1
    assert [row["symbol"] for row in payload["candidates"]] == ["VALUE", "QUALITY"]
