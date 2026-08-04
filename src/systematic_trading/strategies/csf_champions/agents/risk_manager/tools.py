"""Agent tools for the CSF Champions risk manager.

Broker state is read from the Alpaca Trading API via ``config.alpaca_config`` —
never from a Lumibot strategy instance. Screening reuses the strategy's own
``screen()`` policy so the agent sees the same ranking as idea generation.
"""

from typing import Annotated

import yaml
from agent_harness.decorator import Param, agent_tool
from alpaca.trading.client import TradingClient

from systematic_trading.config import alpaca_config
from systematic_trading.strategies.csf_champions.screening import DISPLAY_COLUMNS, screen

DEFAULT_TOP_N = 50

#     ================================
# --> Helper funcs
#     ================================


def _held_tickers() -> set[str]:
    """Open position symbols on the configured Alpaca account (paper or live)."""
    config = alpaca_config()
    client = TradingClient(
        api_key=config["API_KEY"],
        secret_key=config["API_SECRET"],
        paper=config["PAPER"],
    )

    return {position.symbol.upper() for position in client.get_all_positions()}


#     ================================
# --> Tools
#     ================================


@agent_tool(name="RunScreener", safe_parallel=True)
def run_screener(
    top_n: Annotated[
        int,
        Param(
            description=(
                "How many ranked candidates to return after dropping held names "
                f"(default {DEFAULT_TOP_N})."
            ),
            min_val=1.0,
            max_val=200.0,
        ),
    ] = DEFAULT_TOP_N,
) -> str:
    """
    Run the CSF Champions quality/value screen and return the top ranked
    tickers that are not already held in the Alpaca account.

    Held names are excluded so the list is candidates for new capital, not a
    re-ranking of the existing book. Returns YAML: excluded count plus a
    `candidates` list of display metrics, highest score first.
    """
    held = _held_tickers()
    ranked = screen()

    if ranked.empty:
        return "error: screen returned no rows"

    available = ranked[~ranked["symbol"].str.upper().isin(held)]
    top = available.head(int(top_n))

    rows = top[DISPLAY_COLUMNS].to_dict("records")

    for row in rows:
        for key, value in row.items():
            if key != "symbol" and value is not None:
                row[key] = round(float(value), 4)

    payload = {
        "excluded_held": len(held),
        "returned": len(rows),
        "candidates": rows,
    }

    return yaml.safe_dump(payload, sort_keys=False, default_flow_style=False)
