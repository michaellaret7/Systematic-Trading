"""Agent tool: CSF Champions quality/value screen for candidate ranking.

Reuses the strategy's own ``screen()`` policy so every agent sees the same
ranking as idea generation. Callers may exclude tickers (e.g. current holdings)
without coupling the tool to a broker.
"""

from typing import Annotated

import yaml
from agent_harness.decorator import Param, agent_tool

from systematic_trading.strategies.csf_champions.screening import DISPLAY_COLUMNS, screen

DEFAULT_TOP_N = 50

# ====================================
# --> Helper funcs
# ====================================


def _normalize_tickers(tickers: list[str] | None) -> set[str]:
    """Normalize optional ticker input for case-insensitive exclusion."""

    return {ticker.strip().upper() for ticker in tickers or [] if ticker.strip()}


# ====================================
# --> Tool
# ====================================


@agent_tool(name="RunScreener", safe_parallel=True)
def csf_screener_tool(
    top_n: Annotated[
        int,
        Param(
            description=(
                "How many ranked candidates to return after applying exclusions "
                f"(default {DEFAULT_TOP_N})."
            ),
            min_val=1.0,
            max_val=200.0,
        ),
    ] = DEFAULT_TOP_N,
    exclude_tickers: Annotated[
        list[str] | None,
        Param(
            description=(
                "Optional ticker symbols to omit from the ranked candidates, such as "
                "current portfolio holdings. Matching is case-insensitive."
            )
        ),
    ] = None,
) -> str:
    """
    Run the CSF Champions quality/value screen and return the top ranked
    candidates after removing any explicitly excluded tickers.

    Exclusions are applied before selecting ``top_n`` so the requested number
    of available candidates is preserved. Returns YAML with requested and
    matched exclusion counts plus display metrics, highest score first.
    """
    excluded = _normalize_tickers(exclude_tickers)
    ranked = screen()

    if ranked.empty:
        return "error: screen returned no rows"

    available = ranked[~ranked["symbol"].str.upper().isin(excluded)]
    top = available.head(int(top_n))

    rows = top[DISPLAY_COLUMNS].to_dict("records")

    for row in rows:
        for key, value in row.items():
            if key != "symbol" and value is not None:
                row[key] = round(float(value), 4)

    payload = {
        "requested_exclusions": len(excluded),
        "excluded": len(ranked) - len(available),
        "returned": len(rows),
        "candidates": rows,
    }

    return yaml.safe_dump(payload, sort_keys=False, default_flow_style=False)
