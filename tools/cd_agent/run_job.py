"""One run of a CD-agent job: fetch `origin/main`, decide, run from a clean checkout of the fetched commit.

    python3 -m cd_agent.run_job --repo-url URL --state-dir DIR [--cwd SUBDIR] [--on-change] -- COMMAND...

The run, in order: take the job's lock; fetch `main` anonymously over HTTPS;
with `--on-change`, stop if that commit is the one last run successfully;
check the commit out into a freshly created tree under DIR; run COMMAND there
(from SUBDIR, with CD_AGENT_STATE_DIR set to DIR); with `--on-change`, record the commit only if COMMAND exited 0.

Standard library only: the agent host runs this with its own python3.
The state-directory layout and exit codes are in
docs/topics/deploy/cd-agent-runner.md.
"""

from __future__ import annotations

import argparse
import fcntl
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib.parse import urlsplit

BRANCH = "main"
TRACKING_REF = f"refs/remotes/origin/{BRANCH}"
ALLOWED_SCHEME = "https"
REPO_DIR = "repo.git"
TREE_DIR = "tree"
DEPLOYED_FILE = "deployed"
LOCK_FILE = "lock"
STATE_ENV = "CD_AGENT_STATE_DIR"
EX_TEMPFAIL = 75

_COMMIT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


class JobError(Exception):
    """The run could not be carried out; nothing was recorded."""


class Outcome(Enum):
    RAN = "ran"
    UNCHANGED = "unchanged"
    BUSY = "busy"
    FAILED = "failed"


EXIT_STATUS = {Outcome.RAN: 0, Outcome.UNCHANGED: 0, Outcome.BUSY: EX_TEMPFAIL, Outcome.FAILED: 1}


@dataclass(frozen=True)
class Job:
    repo_url: str
    state_dir: Path
    command: tuple[str, ...]
    cwd: str = "."
    on_change: bool = False


def parse_repo_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != ALLOWED_SCHEME:
        raise JobError(f"repo URL must use {ALLOWED_SCHEME}: {url!r}")
    if "@" in parts.netloc:
        raise JobError("repo URL must not carry credentials: the fetch is anonymous")
    return url


def _git_env() -> dict[str, str]:
    # Nothing from the caller's git environment or any git config file may
    # change what is fetched or run: no credential helper, no hooks, no
    # transport but the one allowed.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_ALLOW_PROTOCOL=ALLOWED_SCHEME,
        GIT_TERMINAL_PROMPT="0",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_SYSTEM=os.devnull,
        GIT_CONFIG_COUNT="1",
        GIT_CONFIG_KEY_0="core.hooksPath",
        GIT_CONFIG_VALUE_0=os.devnull,
    )
    return env


def _git(*args: str, repo: Path | None = None) -> str:
    prefix = ["--git-dir", str(repo)] if repo else []
    result = subprocess.run(["git", *prefix, *args], env=_git_env(), capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise JobError(f"git {args[0]} failed: {result.stderr.strip()}")
    return result.stdout


def fetch_origin_main(repo: Path, url: str) -> str:
    """Fetch `main` and nothing else into `repo`; return the commit it points at."""
    if not repo.exists():
        _git("init", "--bare", "--quiet", str(repo))
    _git("fetch", "--quiet", "--no-tags", url, f"+refs/heads/{BRANCH}:{TRACKING_REF}", repo=repo)
    commit = _git("rev-parse", "--verify", f"{TRACKING_REF}^{{commit}}", repo=repo).strip()
    if not _COMMIT.fullmatch(commit):
        raise JobError(f"git returned {commit!r}, not a commit id")
    return commit


def checkout_clean(repo: Path, tree: Path, commit: str) -> None:
    """Replace `tree` with a checkout of exactly `commit`: nothing a previous run left behind survives."""
    if tree.exists():
        shutil.rmtree(tree)
    _git("worktree", "prune", repo=repo)
    _git("worktree", "add", "--detach", "--quiet", str(tree), commit, repo=repo)


def read_deployed(path: Path) -> str | None:
    try:
        text = path.read_text().strip()
    except FileNotFoundError:
        return None
    return text if _COMMIT.fullmatch(text) else None


def write_deployed(path: Path, commit: str) -> None:
    pending = path.with_name(path.name + ".tmp")
    pending.write_text(commit + "\n")
    os.replace(pending, path)


def _workdir(tree: Path, relative: str) -> Path:
    path = (tree / relative).resolve()
    if not path.is_relative_to(tree.resolve()):
        raise JobError(f"--cwd {relative!r} leaves the checkout")
    if not path.is_dir():
        raise JobError(f"--cwd {relative!r} is not a directory in the checked-out commit")
    return path


@contextmanager
def _locked(path: Path) -> Iterator[bool]:
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True


def run_job(job: Job) -> Outcome:
    url = parse_repo_url(job.repo_url)
    state = job.state_dir.resolve()
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    with _locked(state / LOCK_FILE) as acquired:
        if not acquired:
            print("another run of this job holds the lock", file=sys.stderr)
            return Outcome.BUSY
        commit = fetch_origin_main(state / REPO_DIR, url)
        print(f"origin/{BRANCH} is {commit}", flush=True)
        if job.on_change and read_deployed(state / DEPLOYED_FILE) == commit:
            print("already deployed; nothing to do", flush=True)
            return Outcome.UNCHANGED
        tree = state / TREE_DIR
        checkout_clean(state / REPO_DIR, tree, commit)
        workdir = _workdir(tree, job.cwd)
        try:
            result = subprocess.run(job.command, cwd=workdir, env={**os.environ, STATE_ENV: str(state)}, check=False)
        except OSError as exc:
            raise JobError(f"cannot start {job.command[0]!r}: {exc}") from exc
        if result.returncode != 0:
            print(f"command exited {result.returncode}; {commit} not recorded", file=sys.stderr)
            return Outcome.FAILED
        if job.on_change:
            write_deployed(state / DEPLOYED_FILE, commit)
        return Outcome.RAN


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo-url", required=True, help="anonymous https URL of the repository")
    ap.add_argument("--state-dir", type=Path, required=True, help="this job's own directory for the fetched repo, checkout, lock and record")
    ap.add_argument("--cwd", default=".", help="directory inside the checkout to run COMMAND from")
    ap.add_argument("--on-change", action="store_true", help="run only when origin/main differs from the last commit COMMAND succeeded on")
    if "--" not in argv:
        ap.error("COMMAND must follow a literal `--`")
    split = argv.index("--")
    args = ap.parse_args(argv[:split])
    command = tuple(argv[split + 1 :])
    if not command:
        ap.error("COMMAND is empty")

    try:
        outcome = run_job(Job(repo_url=args.repo_url, state_dir=args.state_dir, command=command, cwd=args.cwd, on_change=args.on_change))
    except JobError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return EXIT_STATUS[outcome]


if __name__ == "__main__":
    sys.exit(main())
