"""Shared DynamoDB plumbing for the repository's tables (trade ledger, trade ideas).

Both tables use the same shape — a string partition key plus a
timestamp-prefixed sort key — so the table handle, pagination loop, and
Decimal-to-float conversion live here once.
"""

from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import ConditionBase

from systematic_trading.config import aws_region


def get_table(name: str) -> Any:
    """Handle to one DynamoDB table; credentials come from the environment."""
    # boto3's resource attributes are dynamic; Pyright can't see Table without boto3-stubs.
    return boto3.resource("dynamodb", region_name=aws_region()).Table(name)  # type: ignore[attr-defined]


def from_dynamo(item: dict) -> dict:
    """Convert DynamoDB's ``Decimal`` numerics back to plain floats."""
    return {k: float(v) if isinstance(v, Decimal) else v for k, v in item.items()}


def query_all(
    table: Any,
    key_condition: ConditionBase,
    filter_expression: ConditionBase | None = None,
) -> list[dict]:
    """Every item matching the key condition, following DynamoDB pagination.

    Items come back in sort-key order (chronological for our tables) with
    Decimals already converted to floats.
    """
    items: list[dict] = []
    kwargs: dict = {"KeyConditionExpression": key_condition}

    if filter_expression is not None:
        kwargs["FilterExpression"] = filter_expression

    while True:
        response = table.query(**kwargs)
        items.extend(response["Items"])

        last_key = response.get("LastEvaluatedKey")
        if last_key is None:
            break

        kwargs["ExclusiveStartKey"] = last_key

    return [from_dynamo(item) for item in items]
