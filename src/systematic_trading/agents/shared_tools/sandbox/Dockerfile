FROM python:3.13-slim

# Only what analysis code needs. Deliberately absent: boto3 (would hand the
# sandbox an S3 client), requests, and this repo's own package — the sandbox
# reads parquet from /data and prints, nothing more.
#
# `ta` is the same indicator library the rest of the codebase uses (see
# shared_tools/prices.py), so an agent's RSI matches ours instead of being a
# hand-rolled variant. scipy covers the regressions and distribution work that
# technical screening leans on. polars is for grouped rolling work across the
# whole panel, where it beats pandas; note `ta` takes pandas Series only, so a
# polars frame has to cross back over with `.to_pandas()` for indicators.
RUN pip install --no-cache-dir pandas numpy pyarrow duckdb ta scipy polars

# Never root. The code running here is written by an LLM, so the container is
# treated as hostile: a process that escapes lands as an unprivileged uid.
RUN useradd -u 1000 -m runner
USER runner

# The container runs with --read-only, so every writable path must be a tmpfs
# mount. HOME points at /tmp because pandas, numpy and duckdb all probe the
# home directory for config and cache on import, and a read-only /home/runner
# makes them fail before the agent's code ever runs.
ENV HOME=/tmp
ENV TMPDIR=/tmp

# The tmpfs, not the code mount. duckdb spills to its working directory by
# default, and /work is mounted read-only — leaving cwd there costs the agent
# two iterations discovering it must SET temp_directory by hand.
WORKDIR /tmp
