"""Reset one strategy's DynamoDB state back to a fresh pre-execution slate.

Deletes every ``trade-ledger`` row for the strategy (orders and their fill
state) and moves every ``trade-ideas`` row back to ``pending``, which is the
state the agent submits them in. Everything else on an idea — score, thesis,
reference and max entry prices — is written once at submission and never
mutated, so status is the only field execution dirties.

Intended for iterating on live/paper execution logic: run it between test runs
so the next run sees the same ideas the agent originally produced.

Broker positions are NOT touched. Flatten those yourself first, or the fill
sweep will re-fill the reset ideas from leftover positions.

Usage:
    uv run python scripts/reset_dynamo_tables.py csf_champions
    uv run python scripts/reset_dynamo_tables.py csf_champions --yes
"""

from __future__ import annotations

import argparse

from boto3.dynamodb.conditions import Attr, Key

from systematic_trading.data.repository.dynamo import get_table, query_all
from systematic_trading.data.repository.ideas import TABLE_NAME as IDEAS_TABLE
from systematic_trading.data.repository.ideas import update_idea_status
from systematic_trading.data.repository.ledger import TABLE_NAME as LEDGER_TABLE


#     ================================
# --> Helper funcs
#     ================================


def _ledger_trade_ids(strategy: str) -> list[str]:
    """Every ledger trade_id recorded for one strategy."""
    items = query_all(get_table(LEDGER_TABLE), Key("strategy").eq(strategy))

    return [str(item["trade_id"]) for item in items]


def _dirty_idea_ids(strategy: str) -> list[str]:
    """Ideas for one strategy that execution has moved off ``pending``."""
    items = query_all(
        get_table(IDEAS_TABLE),
        Key("strategy").eq(strategy),
        Attr("status").ne("pending"),
    )

    return [str(item["idea_id"]) for item in items]


def _delete_ledger_rows(strategy: str, trade_ids: list[str]) -> None:
    """Remove the given ledger rows, batching the deletes."""
    table = get_table(LEDGER_TABLE)

    with table.batch_writer() as batch:
        for trade_id in trade_ids:
            batch.delete_item(Key={"strategy": strategy, "trade_id": trade_id})


def _reset_idea_statuses(strategy: str, idea_ids: list[str]) -> None:
    """Move the given ideas back to ``pending``."""
    for idea_id in idea_ids:
        update_idea_status(strategy, idea_id, "pending")


def _confirm(strategy: str, ledger_count: int, idea_count: int) -> bool:
    """Show the blast radius and require a typed confirmation."""
    print(f"Strategy: {strategy}")
    print(f"  {LEDGER_TABLE}: delete {ledger_count:,} rows")
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

    trade_ids = _ledger_trade_ids(strategy)
    idea_ids = _dirty_idea_ids(strategy)

    if not trade_ids and not idea_ids:
        print(f"Nothing to reset for {strategy}.")
        return

    if not args.yes and not _confirm(strategy, len(trade_ids), len(idea_ids)):
        print("Aborted.")
        return

    _delete_ledger_rows(strategy, trade_ids)
    _reset_idea_statuses(strategy, idea_ids)

    print(f"Deleted {len(trade_ids):,} ledger rows; reset {len(idea_ids):,} ideas to 'pending'.")


if __name__ == "__main__":
    main()
