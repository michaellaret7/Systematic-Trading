"""Reset one strategy's DynamoDB ideas and flatten the broker account.

Moves every ``trade-ideas`` row for the strategy back to ``pending`` (the state
the agent submits them in). Everything else on an idea — score, thesis,
reference price — is written once at submission and never mutated, so status
is the only field execution dirties.

It also flattens the broker: cancels every open order and liquidates every
position at market. **This is account-wide** — Alpaca has no notion of our
strategy partition, so it closes every position and order in the account, not
just this strategy's.

Intended for iterating on live/paper execution logic: run it between test runs
so the next run sees the same ideas the agent originally produced.

Paper by default (``ALPACA_PAPER`` controls it). On a live account this
liquidates real money — the mode is shown in the confirmation.

Usage:
    uv run python scripts/reset_strategy_run.py csf_champions
    uv run python scripts/reset_strategy_run.py csf_champions --yes
"""

from __future__ import annotations

import argparse

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import QueryOrderStatus
from alpaca.trading.requests import GetOrdersRequest
from boto3.dynamodb.conditions import Attr, Key

from systematic_trading.config import alpaca_config, is_paper
from systematic_trading.data.repository.dynamo import get_table, query_all
from systematic_trading.data.repository.ideas import TABLE_NAME as IDEAS_TABLE
from systematic_trading.data.repository.ideas import update_idea_status


#     ================================
# --> Helper funcs
#     ================================


def _broker_client() -> TradingClient:
    """Alpaca trading client, paper/live per ``ALPACA_PAPER``."""
    config = alpaca_config()

    return TradingClient(
        api_key=config["API_KEY"],
        secret_key=config["API_SECRET"],
        paper=config["PAPER"],
    )


def _broker_state(client: TradingClient) -> tuple[int, int]:
    """Open-position and open-order counts, for the blast-radius preview."""
    positions = client.get_all_positions()
    open_orders = client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN))

    return len(positions), len(open_orders)


def _flatten_broker(client: TradingClient) -> None:
    """Cancel every open order and liquidate every position at market.

    ``cancel_orders=True`` cancels working orders first, so a resting sell can't
    race the market close and double up.
    """
    client.close_all_positions(cancel_orders=True)


def _dirty_idea_ids(strategy: str) -> list[str]:
    """Ideas for one strategy that execution has moved off ``pending``."""
    items = query_all(
        get_table(IDEAS_TABLE),
        Key("strategy").eq(strategy),
        Attr("status").ne("pending"),
    )

    return [str(item["idea_id"]) for item in items]


def _reset_idea_statuses(strategy: str, idea_ids: list[str]) -> None:
    """Move the given ideas back to ``pending``."""
    for idea_id in idea_ids:
        update_idea_status(strategy, idea_id, "pending")


def _confirm(
    strategy: str,
    idea_count: int,
    position_count: int,
    order_count: int,
) -> bool:
    """Show the blast radius and require a typed confirmation."""
    mode = "PAPER" if is_paper() else "LIVE — REAL MONEY"

    print(f"Strategy: {strategy}")
    print(f"  Alpaca ({mode}) — ACCOUNT-WIDE, not strategy-scoped:")
    print(f"    positions:   close {position_count:,} at market")
    print(f"    open orders: cancel {order_count:,}")
    print(f"  {IDEAS_TABLE}: reset {idea_count:,} ideas to 'pending'")

    return input("Proceed? type 'yes' to confirm: ").strip().lower() == "yes"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("strategy", help="strategy partition key to reset, e.g. csf_champions")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="skip the confirmation prompt",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    strategy = args.strategy

    client = _broker_client()

    idea_ids = _dirty_idea_ids(strategy)
    position_count, order_count = _broker_state(client)

    if not idea_ids and not position_count and not order_count:
        print(f"Nothing to reset for {strategy}.")
        return

    if not args.yes and not _confirm(strategy, len(idea_ids), position_count, order_count):
        print("Aborted.")
        return

    # Flatten the broker first, then clear idea execution state.
    _flatten_broker(client)
    _reset_idea_statuses(strategy, idea_ids)

    print(
        f"Closed {position_count:,} positions and cancelled {order_count:,} orders; "
        f"reset {len(idea_ids):,} ideas to 'pending'."
    )


if __name__ == "__main__":
    main()
