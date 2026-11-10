"""Replay a series on a scratch worktree of the base branch, running the checks at every commit's state.

Nothing is pushed or opened: the worktree is created from the base commit and removed afterwards, and the
repository's own branches are not touched. A commit already in the base is skipped, and a commit that changes
code the replay itself runs stops the replay until the maintainer confirms it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from land_series.manifest import Layer, group_pulls

# A layer touching one of these changes code or configuration that `git am`'s hooks or the checks run on this machine
# before CI sees it; `pyproject.toml` and `uv.lock` decide which packages `uv run` installs and runs. Prefixes, so a path
# with a space in it, which a diff header cannot split reliably, still matches.
STOP_PREFIXES = (".githooks/", ".pre-commit-config.yaml", ".github/workflows/", ".github/actions/", "tools/", "pyproject.toml", "uv.lock")
OUTPUT_TAIL_LINES = 40
_PATH_START = re.compile(r'(?:^|(?<=[ "]))[ab]/')

Confirm = Callable[[Layer, Sequence[str]], bool]


class ReplayError(Exception):
    """The replay stopped at a layer; nothing was pushed."""


@dataclass(frozen=True)
class Check:
    argv: tuple[str, ...]
    cwd: str = "."

    def __str__(self) -> str:
        return " ".join(self.argv)


@dataclass(frozen=True)
class LayerResult:
    layer: Layer
    applied: bool
    commit: str | None = None


def stopped_by(layer: Layer) -> list[str]:
    """What the layer touches that is on the stop list, as its diff headers name it."""
    hits = set()
    for header in layer.diff_headers:
        for match in _PATH_START.finditer(header):
            candidate = header[match.end() :]
            if candidate.startswith(STOP_PREFIXES):
                hits.add(candidate.split(" b/")[0].strip('"'))
    return sorted(hits)


def git_run(repo: Path, *args: str, stdin: bytes | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(repo), *args], input=stdin, capture_output=True, check=False, env={**os.environ, **env} if env else None)


def git_text(result: subprocess.CompletedProcess[bytes]) -> str:
    return (result.stdout + result.stderr).decode("utf-8", errors="replace").strip()


def landed_in(repo: Path, base: str) -> set[tuple[int, str]]:
    """The (author time, subject) of every commit in the base: `git am` keeps both, so a landed layer matches its own commit."""
    result = git_run(repo, "log", base, "--format=%at%x09%s")
    if result.returncode != 0:
        raise ReplayError(f"cannot read the history of {base}: {git_text(result)}")
    pairs = set()
    for line in result.stdout.decode("utf-8", errors="replace").splitlines():
        stamp, _, subject = line.partition("\t")
        pairs.add((int(stamp), " ".join(subject.split())))
    return pairs


@contextmanager
def scratch_worktree(repo: Path, base: str) -> Iterator[Path]:
    parent = Path(tempfile.mkdtemp(prefix="land-series-"))
    tree = parent / "tree"
    try:
        added = git_run(repo, "worktree", "add", "--detach", str(tree), base)
        if added.returncode != 0:
            raise ReplayError(f"cannot create a worktree of {base}: {git_text(added)}")
        try:
            yield tree
        finally:
            git_run(repo, "worktree", "remove", "--force", str(tree))
    finally:
        shutil.rmtree(parent, ignore_errors=True)
        git_run(repo, "worktree", "prune")


def _reset(tree: Path) -> None:
    """Drop what the apply hooks and the checks leave unstaged: the generated views, which stop a second `git am`."""
    git_run(tree, "reset", "--hard", "--quiet")
    git_run(tree, "clean", "--force", "-d", "--quiet")


def apply_layer(tree: Path, layer: Layer, onto: str) -> None:
    """`git am` the layer in `tree` (its apply hooks run), then drop what the hooks left unstaged."""
    applied = git_run(tree, "am", "--quiet", stdin=layer.patch)
    if applied.returncode != 0:
        git_run(tree, "am", "--abort")
        raise ReplayError(f"commit {layer.id} does not apply on {onto}:\n{git_text(applied)}")
    _reset(tree)


def _run_check(tree: Path, check: Check) -> str | None:
    """The tail of the output when the check fails, else None."""
    try:
        result = subprocess.run(check.argv, cwd=tree / check.cwd, capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL)
    except OSError as error:
        return f"cannot run it: {error}"
    if result.returncode == 0:
        return None
    return "\n".join((result.stdout + result.stderr).strip().splitlines()[-OUTPUT_TAIL_LINES:])


Progress = Callable[[str], None]

HOOK_LINK_COMMAND = 'for hook in pre-applypatch post-applypatch; do ln -sf "$PWD/.githooks/$hook" "$(git rev-parse --git-path hooks)/$hook"; done'


def silent(message: str) -> None:
    """The default progress report: none."""


def preflight(repo: Path, base: str) -> list[str]:
    """What the replay needs from this machine and does not find, each with the command or setting that fixes it.

    A base without `.githooks/pre-applypatch` needs no hooks. Without them `git am` skips the checks, or fails deep inside a
    hook, so the problem is named here, before a worktree exists.
    """
    problems = []
    if git_run(repo, "cat-file", "-e", f"{base}:.githooks/pre-applypatch").returncode == 0:
        found = git_run(repo, "rev-parse", "--git-path", "hooks")
        hooks = (repo / git_text(found)) if found.returncode == 0 else repo / ".git" / "hooks"
        missing = [name for name in ("pre-applypatch", "post-applypatch", "pre-commit") if not os.access(hooks / name, os.X_OK)]
        if missing:
            problems.append(f"{', '.join(missing)} not installed in {hooks}: run `pre-commit install`, then `{HOOK_LINK_COMMAND}` from the repository root")
        if shutil.which("pre-commit") is None:
            problems.append("`pre-commit` is not on PATH, and the apply hooks call it: run the tool with `uv run`, or install it")
    if git_run(repo, "var", "GIT_COMMITTER_IDENT").returncode != 0:
        problems.append("git has no committer identity, and `git am` needs one: set user.name and user.email, or GIT_COMMITTER_NAME and GIT_COMMITTER_EMAIL")
    return problems


def replay(
    repo: Path, layers: Sequence[Layer], checks: Sequence[Check], confirm: Confirm, base: str = "origin/main", progress: Progress = silent
) -> list[LayerResult]:
    """Apply each layer, in the order given, on a scratch worktree of `base`; run every check after each.

    Returns what happened to each layer. Raises ReplayError at the first layer that is refused, does not apply or fails a check.
    """
    if problems := preflight(repo, base):
        raise ReplayError("this machine is not ready to replay:\n" + "\n".join(f"- {problem}" for problem in problems))
    landed = landed_in(repo, base)
    for pull in group_pulls(list(layers)):
        present = [(layer.authored, layer.subject) in landed for layer in pull.layers]
        if any(present) and not all(present):
            raise ReplayError(
                f"pull request {pull.number} is partly in {base}: some of its commits are there and some are not; give the rest a number of their own"
            )
    results: list[LayerResult] = []
    with scratch_worktree(repo, base) as tree:
        for layer in layers:
            if (layer.authored, layer.subject) in landed:
                results.append(LayerResult(layer, applied=False))
                continue
            stops = stopped_by(layer)
            if stops and not confirm(layer, stops):
                raise ReplayError(f"commit {layer.id} changes code the replay runs ({', '.join(stops)}) and was not confirmed")
            progress(f"commit {layer.id}: applying the patch on {base}{' plus the layers before it' if results else ''}")
            apply_layer(tree, layer, f"{base}{' plus the layers before it' if results else ''}")
            for check in checks:
                progress(f"commit {layer.id}: running `{check}`")
                failure = _run_check(tree, check)
                _reset(tree)
                if failure is not None:
                    raise ReplayError(f"commit {layer.id} fails `{check}`:\n{failure}")
            results.append(LayerResult(layer, applied=True, commit=git_text(git_run(tree, "rev-parse", "HEAD"))))
    return results
