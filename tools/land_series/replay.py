"""Replay a series on a scratch worktree of the base branch, running the checks at every layer's state.

Nothing is pushed or opened: the worktree is created from the base commit and removed afterwards, and the
repository's own branches are not touched. A layer already in the base is skipped, and a layer that changes
code the replay itself runs stops the replay until the maintainer confirms it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from land_series.manifest import Layer

# A layer touching one of these changes code or configuration that `git am`'s hooks or the checks run on this machine
# before CI sees it. Prefixes, so a path with a space in it, which a diff header cannot split reliably, still matches.
STOP_PREFIXES = (".githooks/", ".pre-commit-config.yaml", ".github/workflows/", ".github/actions/", "tools/")
OUTPUT_TAIL_LINES = 40
_PATH_START = re.compile(r'(?:^|(?<=[ "]))[ab]/')

Confirm = Callable[[Layer, Sequence[str]], bool]


class ReplayError(Exception):
    """The replay stopped at a layer; nothing was pushed."""


@dataclass(frozen=True)
class Check:
    argv: tuple[str, ...]
    cwd: str = "."
    env: Mapping[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        return " ".join(self.argv)


@dataclass(frozen=True)
class LayerResult:
    layer: Layer
    applied: bool


def stopped_by(layer: Layer) -> list[str]:
    """What the layer touches that is on the stop list, as its diff headers name it."""
    hits = set()
    for header in layer.diff_headers:
        for match in _PATH_START.finditer(header):
            candidate = header[match.end() :]
            if candidate.startswith(STOP_PREFIXES):
                hits.add(candidate.split(" b/")[0].strip('"'))
    return sorted(hits)


def _git(repo: Path, *args: str, stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(repo), *args], input=stdin, capture_output=True, check=False)


def _text(result: subprocess.CompletedProcess[bytes]) -> str:
    return (result.stdout + result.stderr).decode("utf-8", errors="replace").strip()


def _landed(repo: Path, base: str) -> set[tuple[int, str]]:
    """The (author time, subject) of every commit in the base: `git am` keeps both, so a landed layer matches its own commit."""
    result = _git(repo, "log", base, "--format=%at%x09%s")
    if result.returncode != 0:
        raise ReplayError(f"cannot read the history of {base}: {_text(result)}")
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
        added = _git(repo, "worktree", "add", "--detach", str(tree), base)
        if added.returncode != 0:
            raise ReplayError(f"cannot create a worktree of {base}: {_text(added)}")
        try:
            yield tree
        finally:
            _git(repo, "worktree", "remove", "--force", str(tree))
    finally:
        shutil.rmtree(parent, ignore_errors=True)
        _git(repo, "worktree", "prune")


def _reset(tree: Path) -> None:
    """Drop what the apply hooks and the checks leave unstaged: the generated views, which stop a second `git am`."""
    _git(tree, "reset", "--hard", "--quiet")
    _git(tree, "clean", "--force", "-d", "--quiet")


def _run_check(tree: Path, check: Check) -> str | None:
    """The tail of the output when the check fails, else None."""
    try:
        result = subprocess.run(
            check.argv, cwd=tree / check.cwd, env={**os.environ, **check.env}, capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL
        )
    except OSError as error:
        return f"cannot run it: {error}"
    if result.returncode == 0:
        return None
    return "\n".join((result.stdout + result.stderr).strip().splitlines()[-OUTPUT_TAIL_LINES:])


def replay(repo: Path, layers: Sequence[Layer], checks: Sequence[Check], confirm: Confirm, base: str = "origin/main") -> list[LayerResult]:
    """Apply each layer, in the order given, on a scratch worktree of `base`; run every check after each.

    Returns what happened to each layer. Raises ReplayError at the first layer that is refused, does not apply or fails a check.
    """
    landed = _landed(repo, base)
    results: list[LayerResult] = []
    with scratch_worktree(repo, base) as tree:
        for layer in layers:
            if (layer.authored, layer.subject) in landed:
                results.append(LayerResult(layer, applied=False))
                continue
            stops = stopped_by(layer)
            if stops and not confirm(layer, stops):
                raise ReplayError(f"layer {layer.id} changes code the replay runs ({', '.join(stops)}) and was not confirmed")
            applied = _git(tree, "am", "--quiet", stdin=layer.patch)
            if applied.returncode != 0:
                _git(tree, "am", "--abort")
                raise ReplayError(f"layer {layer.id} does not apply on {base}{' plus the layers before it' if results else ''}:\n{_text(applied)}")
            _reset(tree)
            for check in checks:
                failure = _run_check(tree, check)
                _reset(tree)
                if failure is not None:
                    raise ReplayError(f"layer {layer.id} fails `{check}`:\n{failure}")
            results.append(LayerResult(layer, applied=True))
    return results
