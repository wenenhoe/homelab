"""Build a job's tools from the commit it is running, then run its command there.

    python3 -m cd_agent.toolchain [--collections FILE] [--python PATH] -- COMMAND...

A job's command, started by cd_agent.run_job from inside the checkout with
CD_AGENT_STATE_DIR set. It installs the locked Python environment into
$CD_AGENT_STATE_DIR/toolchain/venv with `uv sync --locked --no-dev`, installs
the Ansible collections FILE names (relative to the working directory) into
$CD_AGENT_STATE_DIR/toolchain/collections, then replaces itself with COMMAND,
which finds the environment first on PATH. The tools therefore always match
the commit being run, and no job shares an environment with another.

Standard library only, like run_job.py. The layout and what is not covered are
in docs/topics/deploy/cd-agent-runner.md.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

LOCK_FILE = "uv.lock"
STATE_ENV = "CD_AGENT_STATE_DIR"


class ToolchainError(Exception):
    """The tools could not be prepared; COMMAND was not run."""


def find_root(start: Path) -> Path:
    """The checkout's root: the nearest directory at or above `start` that holds the lock file."""
    for directory in (start, *start.parents):
        if (directory / LOCK_FILE).is_file():
            return directory
    raise ToolchainError(f"no {LOCK_FILE} at or above {start}")


def toolchain_dir() -> Path:
    state = os.environ.get(STATE_ENV)
    if not state:
        raise ToolchainError(f"{STATE_ENV} is not set: run this as a cd_agent.run_job command")
    return Path(state) / "toolchain"


def _run(argv: list[str], env: dict[str, str]) -> None:
    try:
        result = subprocess.run(argv, env=env, check=False)
    except FileNotFoundError as exc:
        raise ToolchainError(f"{argv[0]} not found on PATH") from exc
    if result.returncode != 0:
        raise ToolchainError(f"{' '.join(argv[:3])} exited {result.returncode}")


def sync_environment(root: Path, directory: Path, python: str) -> Path:
    """Install what the lock names, and nothing else, into a venv of its own; return the venv."""
    venv = directory / "venv"
    env = {
        **os.environ,
        "UV_PROJECT_ENVIRONMENT": str(venv),
        "UV_CACHE_DIR": str(directory / "uv-cache"),
        "UV_PYTHON_DOWNLOADS": "never",
    }
    # --locked, not --frozen: a lock that no longer matches pyproject.toml stops the run.
    _run(["uv", "sync", "--locked", "--no-dev", "--project", str(root), "--python", python], env)
    return venv


def install_collections(root: Path, requirements: Path, directory: Path, venv: Path) -> Path:
    path = requirements.resolve()
    if not path.is_relative_to(root.resolve()):
        raise ToolchainError(f"--collections {requirements} leaves the checkout")
    collections = directory / "collections"
    env = {**os.environ, "PATH": f"{venv / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}"}
    _run(["ansible-galaxy", "collection", "install", "-r", str(path), "-p", str(collections)], env)
    return collections


def command_environment(venv: Path, collections: Path | None) -> dict[str, str]:
    env = {**os.environ, "VIRTUAL_ENV": str(venv), "PATH": f"{venv / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}"}
    env.pop("PYTHONHOME", None)
    if collections is not None:
        env["ANSIBLE_COLLECTIONS_PATH"] = str(collections)
    return env


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--collections", type=Path, help="Ansible requirements file, relative to the working directory")
    ap.add_argument("--python", default=sys.executable, help="interpreter for the environment (default: the one running this)")
    if "--" not in argv:
        ap.error("COMMAND must follow a literal `--`")
    split = argv.index("--")
    args = ap.parse_args(argv[:split])
    command = argv[split + 1 :]
    if not command:
        ap.error("COMMAND is empty")

    try:
        root = find_root(Path.cwd())
        directory = toolchain_dir()
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        venv = sync_environment(root, directory, args.python)
        collections = install_collections(root, args.collections, directory, venv) if args.collections else None
    except ToolchainError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    env = command_environment(venv, collections)
    try:
        os.execvpe(command[0], command, env)  # noqa: S606 - the command is the job's own, from its definition
    except OSError as exc:
        print(f"error: cannot start {command[0]!r}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
