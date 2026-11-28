"""Replay the series on a fresh clone of the base the way the maintainer will, then run the push stage of each pull request."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from land_series.__main__ import default_push_checks
from land_series.run import CommandError, checked

from deliver_series.build import Layer
from deliver_series.repo import RepoError, git, patch_of, rev
from deliver_series.repository import HOMELAB, Identity

TAIL_LINES = 40
CLONE_SECONDS = 600
SHIM = f'#!/bin/bash\nexec uvx --python {HOMELAB.python} pre-commit "$@"\n'

Progress = Callable[[str], None]


class VerifyError(Exception):
    """The series did not pass the replay or the push stage, or the machine cannot run them."""


@dataclass(frozen=True)
class Machine:
    """What the clone and the checks run with: the committer identity `git am` needs, the hooks to skip, and a `pre-commit` on PATH."""

    identity: Identity
    skips: Mapping[str, str]
    shim: Path | None

    def env(self, **extra: str) -> dict[str, str]:
        env = {**os.environ, "GIT_COMMITTER_NAME": self.identity.name, "GIT_COMMITTER_EMAIL": self.identity.email, **extra}
        if self.skips:
            env["SKIP"] = ",".join(self.skips)
        else:
            env.pop("SKIP", None)
        if self.shim:
            env["PATH"] = f"{self.shim}{os.pathsep}{env['PATH']}"
        return env


def make_shim(directory: Path) -> Path | None:
    """A directory holding a `pre-commit` that runs through `uvx`, when none is on PATH; None when one is."""
    if shutil.which("pre-commit"):
        return None
    if not shutil.which("uvx"):
        raise VerifyError("neither `pre-commit` nor `uvx` is on PATH, so the hooks cannot run")
    shim = directory / "pre-commit"
    shim.write_text(SHIM)
    shim.chmod(0o755)
    return directory


@contextmanager
def fresh_clone(origin: str, base_ref: str, expected: str, machine: Machine, progress: Progress):
    """A full clone of the remote with its hooks installed, whose base is still the commit the series was built on."""
    parent = Path(tempfile.mkdtemp(prefix="deliver-series-"))
    try:
        clone = parent / "clone"
        progress(f"cloning {origin}")
        try:
            checked(["git", "clone", "--quiet", origin, str(clone)], timeout=CLONE_SECONDS)
        except CommandError as error:
            raise VerifyError(f"cannot clone {origin}: {error}") from error
        if (now := rev(clone, base_ref)) != expected:
            raise VerifyError(f"{base_ref} moved to {now[:12]} while the series was built on {expected[:12]}; build it again")
        installed = subprocess.run(["pre-commit", "install"], cwd=clone, env=machine.env(), capture_output=True, check=False)
        if installed.returncode != 0:
            raise VerifyError(f"`pre-commit install` failed:\n{installed.stderr.decode(errors='replace').strip()}")
        yield clone
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def _tail(text: str) -> str:
    return "\n".join(text.strip().splitlines()[-TAIL_LINES:])


def replay(clone: Path, series: Path, base_ref: str, machine: Machine, tools: Path, log: Path, progress: Progress) -> None:
    """`land_series --dry-run` on the clone. Its output goes to `log`, which a run that takes minutes can be followed in."""
    argv = [sys.executable, "-m", "land_series", str(series), "--repo", str(clone), "--base", base_ref, "--no-fetch", "--dry-run", "--accept-stops"]
    progress(f"replaying; follow it with `tail -f {log}`")
    with log.open("wb") as out:
        done = subprocess.run(argv, cwd=tools, env=machine.env(), stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, check=False)
    if done.returncode != 0:
        raise VerifyError(f"the replay failed (exit {done.returncode}):\n{_tail(log.read_text(errors='replace'))}\nThe whole log is {log}.")


def apply_series(clone: Path, layers: list[Layer], repo: Path, base_ref: str, machine: Machine) -> dict[str, tuple[str, str]]:
    """Apply every commit on a branch of the clone with hooks off; return, for each pull request number, the commit before it and its last one."""
    git(clone, "switch", "--quiet", "--detach", base_ref)
    spans: dict[str, tuple[str, str]] = {}
    for layer in layers:
        before = rev(clone, "HEAD")
        for commit in layer.commits:
            applied = subprocess.run(
                ["git", "-C", str(clone), "-c", "core.hooksPath=/dev/null", "am", "--quiet"],
                input=patch_of(repo, commit.sha),
                env=machine.env(),
                capture_output=True,
                check=False,
            )
            if applied.returncode != 0:
                subprocess.run(["git", "-C", str(clone), "am", "--abort"], capture_output=True, check=False)
                raise VerifyError(f"{commit.sha[:12]} does not apply for the push stage: {applied.stderr.decode(errors='replace').strip()}")
        spans[f"{layer.number:04d}"] = (before, rev(clone, "HEAD"))
    return spans


def push_stage(clone: Path, spans: Mapping[str, tuple[str, str]], machine: Machine, progress: Progress) -> None:
    """What `git push` would run for each pull request: the pre-push hooks over its own commits, on its last commit, as `--land` runs them."""
    for number, (before, last) in spans.items():
        git(clone, "switch", "--quiet", "--detach", last)
        for check in (check.at(before) for check in default_push_checks()):
            progress(f"pull request {number}: running the pre-push hooks")
            done = subprocess.run(check.argv, cwd=clone, env=machine.env(), capture_output=True, text=True, errors="replace", check=False)
            if done.returncode != 0:
                raise VerifyError(f"pull request {number} fails the push stage:\n{_tail(done.stdout + done.stderr)}")


def verify(repo: Path, layers: list[Layer], series: Path, base: str, machine: Machine, tools: Path, log: Path, progress: Progress, expected: str) -> None:
    base_ref = f"{HOMELAB.remote}/{base}"
    try:
        with fresh_clone(git(repo, "remote", "get-url", HOMELAB.remote), base_ref, expected, machine, progress) as clone:
            replay(clone, series, base_ref, machine, tools, log, progress)
            push_stage(clone, apply_series(clone, layers, repo, base_ref, machine), machine, progress)
    except (RepoError, OSError) as error:
        raise VerifyError(str(error)) from error
