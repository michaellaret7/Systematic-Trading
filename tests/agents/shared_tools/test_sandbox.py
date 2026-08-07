"""Sandbox tests: real code, real repository data, real containers.

Every case here runs an actual container against the actual parquet snapshot —
the isolation claims are worth nothing if they are only asserted against mocks.
The suite is skipped when Docker is unavailable, since the sandbox has no
meaning without it.
"""

import pyarrow.parquet as pq
import pytest
from dotenv import dotenv_values

from systematic_trading.agents.shared_tools.sandbox.runner import docker_available, run_code
from systematic_trading.cloud.bootstrap import ENV_FILE
from systematic_trading.agents.shared_tools.sandbox.sync import sync_snapshot
from systematic_trading.agents.shared_tools.sandbox.tool import run_python
from systematic_trading.config import sandbox_data_dir

pytestmark = pytest.mark.skipif(
    not docker_available(), reason="the code sandbox requires a running Docker daemon"
)


@pytest.fixture(scope="module", autouse=True)
def snapshot():
    """Ensure the local data snapshot exists before any container runs."""
    sync_snapshot()


# ====================================
# --> Analysis over real data
# ====================================


def test_duckdb_row_count_matches_the_parquet_metadata():
    """A duckdb scan inside the sandbox agrees with the file's own metadata."""
    expected = pq.ParquetFile(sandbox_data_dir() / "prices.parquet").metadata.num_rows

    result = run_code(
        "import duckdb\n"
        "print(duckdb.sql(\"SELECT count(*) FROM '/data/prices.parquet'\").fetchone()[0])"
    )

    assert result.ok, result.stderr
    assert int(result.stdout.strip()) == expected


def test_pandas_sma_matches_a_host_side_computation():
    """A 200-day SMA computed in the sandbox matches the same figure computed here."""
    import pandas as pd

    frame = pd.read_parquet(
        sandbox_data_dir() / "prices.parquet", filters=[("symbol", "==", "AAPL")]
    )
    expected = frame.sort_values("date")["close"].tail(200).mean()

    result = run_code(
        "import pandas as pd\n"
        "f = pd.read_parquet('/data/prices.parquet', filters=[('symbol', '==', 'AAPL')])\n"
        "print(f.sort_values('date')['close'].tail(200).mean())"
    )

    assert result.ok, result.stderr
    assert float(result.stdout.strip()) == pytest.approx(expected)


def test_fundamentals_panel_is_mounted_and_readable():
    """The built panel is present in the snapshot and queryable by the agent."""
    result = run_code(
        "import duckdb\n"
        "print(duckdb.sql(\"SELECT count(*) FROM '/data/fundamentals_panel.parquet'\").fetchone()[0])"
    )

    assert result.ok, result.stderr
    assert int(result.stdout.strip()) > 0


def test_raw_statements_are_mounted():
    """All ten raw statement files reached the snapshot, not just the panel."""
    result = run_code(
        "import glob\nprint(len(glob.glob('/data/*_quarter.parquet') + glob.glob('/data/*_annual.parquet')))"
    )

    assert result.ok, result.stderr
    assert int(result.stdout.strip()) == 10


# ====================================
# --> Isolation
# ====================================


def test_the_sandbox_has_no_network():
    """Outbound sockets fail — this is what makes withholding credentials meaningful."""
    result = run_code(
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=5)\n"
        "    print('REACHED')\n"
        "except OSError:\n"
        "    print('BLOCKED')"
    )

    assert result.ok, result.stderr
    assert result.stdout.strip() == "BLOCKED"


def test_the_sandbox_inherits_no_credentials():
    """None of the host's .env variable names exist inside the container.

    Matched against the real key list rather than a substring like "KEY":
    python:3.13-slim sets ``GPG_KEY`` itself to verify the Python tarball, so a
    substring test fails on the base image while proving nothing about ours.
    """
    host_keys = set(dotenv_values(ENV_FILE))

    result = run_code("import os\nprint('\\n'.join(sorted(os.environ)))")

    assert result.ok, result.stderr
    assert host_keys, "no .env keys to check against"
    assert not host_keys & set(result.stdout.split())


def test_the_filesystem_is_read_only():
    """Code cannot write outside the tmpfs, including into the mounted data."""
    result = run_code(
        "try:\n"
        "    open('/data/prices.parquet', 'w').close()\n"
        "    print('WROTE')\n"
        "except OSError:\n"
        "    print('BLOCKED')"
    )

    assert result.ok, result.stderr
    assert result.stdout.strip() == "BLOCKED"


def test_a_memory_hog_is_killed_not_the_host():
    """Allocating past the cap kills the container and reports it as an OOM."""
    result = run_code("x = bytearray(4 * 1024**3)\nprint('ALLOCATED')", memory="256m")

    assert not result.ok
    assert "ALLOCATED" not in result.stdout


def test_an_infinite_loop_is_timed_out():
    """A runaway loop is stopped rather than holding memory against the strategy."""
    result = run_code("while True:\n    pass", timeout_seconds=10)

    assert result.timed_out


# ====================================
# --> Tool surface
# ====================================


def test_the_tool_returns_printed_output():
    """The agent-facing tool hands back exactly what the code printed."""
    assert run_python("print(6 * 7)").strip() == "42"


def test_the_tool_returns_a_traceback_the_agent_can_act_on():
    """A fault comes back as readable text rather than raising."""
    output = run_python("import pandas as pd\npd.read_parquet('/data/nope.parquet')")

    assert output.startswith("error:")
    assert "nope.parquet" in output


def test_output_printed_before_a_failure_survives():
    """Partial output is kept, so a later fault does not discard earlier work.

    Observed live: an agent printed a schema, crashed on the next statement, and
    spent an entire extra turn re-running the DESCRIBE it had already answered.
    """
    output = run_python("print('SCHEMA HERE')\nraise ValueError('boom')")

    assert "SCHEMA HERE" in output
    assert "boom" in output
