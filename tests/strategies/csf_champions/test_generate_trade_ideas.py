"""CSF Champions idea-generation workflow boundary."""

from typing import Any

import pandas as pd
import pytest

from systematic_trading.strategies.csf_champions.workflows import generate_trade_ideas


class FakeAgent:
    """Record candidate analysis without calling an LLM."""

    def __init__(self, analyzed: list[str]) -> None:
        self._analyzed = analyzed

    def run(self, task: str, sink: Any) -> None:
        """Capture the symbol embedded in the workflow task."""
        symbol = task.split("ticker: ", maxsplit=1)[1].split(",", maxsplit=1)[0]

        if symbol == "FAIL":
            raise RuntimeError("analysis failed")

        self._analyzed.append(symbol)


def test_generate_trade_ideas_isolates_candidate_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One failed agent does not stop the remaining candidate analyses."""
    analyzed: list[str] = []
    ranked = pd.DataFrame({"symbol": ["AAPL", "FAIL", "MSFT"]})

    # Every outbound boundary is stubbed — screen, the FMP name lookup, the
    # idea-count query, and the agent — so the test stays offline.
    monkeypatch.setattr(generate_trade_ideas, "screen", lambda: ranked)
    monkeypatch.setattr(
        generate_trade_ideas, "company_names", lambda syms: {s: f"{s} Inc." for s in syms}
    )
    monkeypatch.setattr(generate_trade_ideas, "count_ideas_since", lambda strategy, since: 0)
    monkeypatch.setattr(generate_trade_ideas, "build_ticker_analyst", lambda: FakeAgent(analyzed))
    monkeypatch.setattr(generate_trade_ideas, "MAX_WORKERS", 1)

    generate_trade_ideas.generate_trade_ideas()

    assert analyzed == ["AAPL", "MSFT"]
