"""Run agent-written Python inside a locked-down Docker container.

The container is the safety boundary, not a convenience. Code reaching here was
written by an LLM, so it is treated as hostile: no network, no writable
filesystem, no root, capped memory/CPU/processes, and — critically — no
environment. The host process carries the whole forwarded ``.env``
(``cloud.digitalocean.env_snippet``), including ``DIGITALOCEAN_TOKEN`` and the
Alpaca keys, so passing ``-e`` flags or using a plain subprocess would hand the
sandbox the ability to place orders and destroy droplets.

Data reaches the container the only way that keeps ``--network none`` intact: a
read-only bind mount of a snapshot already on disk (see ``sandbox_snippet`` in
``cloud.digitalocean``), never a live S3 read from inside.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from systematic_trading.config import sandbox_data_dir

IMAGE = "sandbox"

# Wall-clock ceiling on one run. Research queries over the full universe finish
# in seconds; anything past this is a runaway loop, not slow analysis.
DEFAULT_TIMEOUT_SECONDS = 60

# Sized against the measured snapshot: the raw statements plus the panel plus
# prices total ~750 MB in memory if the agent loads every file at once, leaving
# room to actually compute on top. The droplet is 4 GB and the live strategy
# holds 1.2 GB, so this is the largest cap that still leaves the strategy —
# which places real orders — comfortably clear of the OOM killer.
DEFAULT_MEMORY = "1500m"
DEFAULT_CPUS = "1"

# Threads count toward the pids cgroup, not just processes, and duckdb spawns
# one per core. 128 stops a fork bomb while leaving normal threading alone.
PIDS_LIMIT = "128"

# Exit code Docker reports when the kernel OOM-kills PID 1 in the container
# (128 + SIGKILL). Worth naming because it is the failure the memory cap exists
# to produce, and the agent can act on it by projecting fewer columns.
OOM_EXIT_CODE = 137


@dataclass(frozen=True)
class SandboxResult:
    """Outcome of one sandbox run: what the code printed and how it ended."""

    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    @property
    def oom_killed(self) -> bool:
        return self.exit_code == OOM_EXIT_CODE


# ====================================
# --> Helper funcs
# ====================================


def docker_available() -> bool:
    """Whether a Docker daemon is reachable from this process."""
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=10, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False

    return result.returncode == 0


def _docker_command(
    container: str, code_dir: Path, data_dir: Path, memory: str, cpus: str
) -> list[str]:
    """Build the ``docker run`` argv, with every isolation flag applied.

    No ``-e`` flags anywhere: the environment is the thing being withheld.
    """
    return [
        "docker", "run", "--rm",
        "--name", container,
        # No route out. The sandbox cannot reach S3, the broker, or the internet,
        # which is what makes withholding credentials meaningful.
        "--network", "none",
        # Immutable root filesystem; /tmp is the one writable place, and it is a
        # tmpfs that dies with the container. `noexec` stops code from staging a
        # binary there and running it.
        "--read-only",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m",
        "--memory", memory,
        # Denying swap makes the memory cap a real ceiling rather than a
        # threshold the container pages past, slowly, while starving the strategy.
        "--memory-swap", memory,
        "--cpus", cpus,
        "--pids-limit", PIDS_LIMIT,
        "--user", "1000:1000",
        # Drop every Linux capability and block privilege escalation, so a setuid
        # binary in the base image cannot be used to climb back to root.
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "-v", f"{data_dir}:/data:ro",
        "-v", f"{code_dir}:/work:ro",
        IMAGE,
        "python", "/work/main.py",
    ]  # fmt: skip


# ====================================
# --> Public API
# ====================================


def run_code(
    code: str,
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    memory: str = DEFAULT_MEMORY,
    cpus: str = DEFAULT_CPUS,
) -> SandboxResult:
    """Execute ``code`` in a throwaway container and return what it printed.

    Raises ``RuntimeError`` only for setup problems the agent cannot fix — a
    missing daemon or snapshot. Faults in the code itself come back as a
    non-zero ``SandboxResult`` so the agent can read the traceback and retry.
    """
    data_dir = sandbox_data_dir()

    if not data_dir.is_dir():
        # Name the env var, not just the sync command: the default path only
        # exists on a droplet, so a local run lands here with the snapshot
        # already downloaded somewhere else and re-syncing would not fix it.
        raise RuntimeError(
            f"No sandbox data snapshot at {data_dir}. Set SANDBOX_DATA_DIR to a local "
            "path, then populate it with "
            "`uv run python -m systematic_trading.agents.shared_tools.sandbox.sync`."
        )

    if not docker_available():
        raise RuntimeError("Docker is not running — the sandbox cannot execute code without it.")

    container = f"sbx-{uuid4().hex[:12]}"

    with tempfile.TemporaryDirectory(prefix="sbx-") as code_dir:
        Path(code_dir, "main.py").write_text(code)

        command = _docker_command(container, Path(code_dir), data_dir, memory, cpus)

        try:
            process = subprocess.run(
                command, capture_output=True, text=True, timeout=timeout_seconds, check=False
            )

        except subprocess.TimeoutExpired:
            # `--rm` only fires when the container exits on its own. Killing the
            # client here would otherwise leave the container running and holding
            # its memory reservation against the live strategy.
            subprocess.run(["docker", "rm", "-f", container], capture_output=True, check=False)

            return SandboxResult("", "", exit_code=-1, timed_out=True)

    return SandboxResult(process.stdout, process.stderr, process.returncode)
