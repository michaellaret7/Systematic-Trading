"""Agent tool: submit a trade idea to the DynamoDB trade-ideas repository.

The LLM supplies only the idea itself (ticker, side, allocation, thesis).
Everything it shouldn't control is stamped by the tool: strategy and model
are injected at wiring time via ``bind_tool`` (hidden underscore params), the
reference price comes from the daily prices repository, and the submission
timestamp is the wall clock — ideas are a live-agent flow, never a backtest.
"""

from datetime import datetime, timezone
from typing import Annotated, Literal

from agent_harness.decorator import Param, agent_tool

from systematic_trading.data.repository import load_daily_prices, submit_idea
from systematic_trading.domain.ideas import TradeIdea

#     ================================
# --> Helper funcs
#     ================================


def _latest_close(symbol: str) -> float | None:
    """Most recent daily close for one symbol; None if it isn't in the repository."""
    frame = load_daily_prices(symbols=[symbol], columns=["symbol", "date", "close"])

    if frame.empty:
        return None

    return float(frame.sort_values("date")["close"].iloc[-1])


#     ================================
# --> Tool
#     ================================


@agent_tool(name="SubmitTradeIdea")
def submit_trade_idea(
    ticker: Annotated[str, Param(description="Ticker symbol, e.g. 'AAPL'.")],
    side: Annotated[
        Literal["long", "short"],
        Param(description="Direction of the idea: 'long' to buy, 'short' to sell short."),
    ],
    score: Annotated[
        float,
        Param(
            description="Your 1-10 conviction score for the business at today's price.",
            min_val=1.0,
            max_val=10.0,
        ),
    ],
    allocation_pct: Annotated[
        float,
        Param(
            description="Portfolio allocation as a percentage, from 0.5 (min) to 3.0 (max).",
            min_val=0.5,
            max_val=3.0,
        ),
    ],
    thesis: Annotated[
        str,
        Param(
            description=(
                "The investment thesis: the specific, evidence-backed reasoning behind "
                "the idea, citing the fundamentals that drove it."
            )
        ),
    ],
    _strategy: str,
    _model: str,
) -> str:
    """
    Submit a trade idea to the strategy's trade-ideas queue. The idea is
    recorded as 'pending' with the current reference price and reviewed for
    execution downstream — submitting is a proposal, not an order.

    Submit at most one idea per ticker; duplicates clutter the queue. An
    unknown ticker returns an "error: ..." string. On success, returns a
    confirmation with the generated idea id and the recorded reference price.
    """
    symbol = ticker.strip().upper()

    if not thesis.strip():
        return "error: thesis must not be empty"

    reference_price = _latest_close(symbol)

    if reference_price is None:
        return f"error: no price data for ticker {symbol!r}; is the symbol correct?"

    idea_id = submit_idea(
        TradeIdea(
            strategy=_strategy,
            ticker=symbol,
            side=side,
            score=score,
            allocation_pct=allocation_pct,
            thesis=thesis.strip(),
            reference_price=reference_price,
            model=_model,
            created_at=datetime.now(timezone.utc),
        )
    )

    return (
        f"recorded trade idea {idea_id}: {side} {symbol} at {allocation_pct}% of portfolio "
        f"(reference price ${reference_price:,.2f}, status: pending)"
    )
