"""Mirror the S3 data repository into the local sandbox snapshot directory.

For local development and tests. On a strategy droplet the same snapshot is
built by ``aws s3 cp`` in the cloud bootstrap rather than here — the bootstrap
must work when the project venv does not, so it cannot route through ``uv``.
The two therefore duplicate the object list; ``SNAPSHOT`` below is the
authority, and ``cloud.digitalocean.sandbox_snippet`` mirrors it.

Run with::

    uv run python -m systematic_trading.agents.shared_tools.sandbox.sync
"""

from __future__ import annotations

import boto3

from systematic_trading.config import s3_bucket, sandbox_data_dir
from systematic_trading.data.repository.fundamentals import PANEL_KEY, PERIODS, STATEMENTS
from systematic_trading.data.repository.prices import DAILY_PRICES_KEY

# S3 key -> file name inside the snapshot. Flattened on purpose: the agent sees
# one directory of parquet files, so its code never has to reason about the
# repository's internal prefixes.
SNAPSHOT: dict[str, str] = {
    DAILY_PRICES_KEY: "prices.parquet",
    PANEL_KEY: "fundamentals_panel.parquet",
    **{
        f"fundamentals/{statement}_{period}.parquet": f"{statement}_{period}.parquet"
        for statement in STATEMENTS
        for period in PERIODS
    },
}


def sync_snapshot() -> None:
    """Download every snapshot object whose local copy is missing or stale."""
    client = boto3.client("s3")
    bucket = s3_bucket()
    target = sandbox_data_dir()

    target.mkdir(parents=True, exist_ok=True)

    for key, filename in SNAPSHOT.items():
        destination = target / filename
        remote_size = client.head_object(Bucket=bucket, Key=key)["ContentLength"]

        # Size is enough to catch a rewrite: push_daily_prices and
        # push_fundamentals rebuild whole files, they never patch in place.
        if destination.exists() and destination.stat().st_size == remote_size:
            print(f"  ok      {filename}")
            continue

        print(f"  pulling {filename} ({remote_size / 1e6:.1f} MB)")
        client.download_file(bucket, key, str(destination))

    print(f"Snapshot ready at {target}")


if __name__ == "__main__":
    sync_snapshot()
