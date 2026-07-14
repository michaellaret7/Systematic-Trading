"""Remove invalid instruments from every stored parquet dataset.

With no symbol arguments, the shared universe denylist is used. Runs are dry
by default; pass ``--apply`` to overwrite the affected S3 parquets.

Usage:
    uv run python scripts/prune_parquet_symbols.py
    uv run python scripts/prune_parquet_symbols.py --apply
    uv run python scripts/prune_parquet_symbols.py DUKB SOJC --apply
"""

from __future__ import annotations

import argparse
from collections.abc import Callable

import pandas as pd

from systematic_trading.data.repository import (
    PERIODS,
    STATEMENTS,
    daily_prices_uri,
    load_daily_prices,
    load_panel,
    load_statement,
    panel_uri,
    statement_uri,
    write_daily_prices,
    write_panel,
    write_statement,
)
from systematic_trading.data.universe import EXCLUDED_SYMBOLS, drop_symbols


def process_dataset(
    label: str,
    uri: str,
    load: Callable[[], pd.DataFrame],
    write: Callable[[pd.DataFrame], None],
    symbols: set[str],
    apply: bool,
) -> int:
    """Prune one dataset, optionally write it, and report removed rows."""
    frame = load()
    cleaned, removed = drop_symbols(frame, symbols)
    action = "removed" if apply else "would remove"

    print(f"[{label}] {action} {removed:,} of {len(frame):,} rows from {uri}")

    if apply and removed:
        write(cleaned)

    return removed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "symbols",
        nargs="*",
        help="symbols to remove; defaults to the shared invalid-instrument denylist",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="overwrite affected parquets; without this flag the script is a dry run",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    symbols = {symbol.upper() for symbol in args.symbols} or set(EXCLUDED_SYMBOLS)
    mode = "APPLY" if args.apply else "DRY RUN"

    print(f"Mode: {mode}")
    print(f"Symbols: {', '.join(sorted(symbols))}")

    total_removed = 0

    for period in PERIODS:
        for statement in STATEMENTS:
            label = f"{statement}_{period}"
            total_removed += process_dataset(
                label=label,
                uri=statement_uri(statement, period),
                load=lambda statement=statement, period=period: load_statement(statement, period),
                write=lambda frame, statement=statement, period=period: write_statement(
                    frame, statement, period
                ),
                symbols=symbols,
                apply=args.apply,
            )

    total_removed += process_dataset(
        label="fundamentals_panel",
        uri=panel_uri(),
        load=load_panel,
        write=write_panel,
        symbols=symbols,
        apply=args.apply,
    )
    total_removed += process_dataset(
        label="daily_prices",
        uri=daily_prices_uri(),
        load=load_daily_prices,
        write=write_daily_prices,
        symbols=symbols,
        apply=args.apply,
    )

    verb = "Removed" if args.apply else "Would remove"
    print(f"{verb} {total_removed:,} rows across all datasets.")


if __name__ == "__main__":
    main()
