"""Replay a series on a scratch worktree of the base branch, running the checks at every commit's state.

Nothing is pushed or opened: the worktree is created from the base commit and removed afterwards, and the
repository's own branches are not touched. A commit already in the base is skipped. Every commit is applied once
before any check runs, and the commits that change code the replay itself runs are put to the maintainer together,
who confirms them or stops the replay.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from land_series.live import Display, hidden
from land_series.manifest import Layer, group_pulls
from land_series.review import Change, Stop
from land_series.run import Completed, run

# A layer touching one of these changes code or configuration that a hook or the checks run on this machine
# before CI sees it; `pyproject.toml` and `uv.lock` decide which packages `uv run` installs and runs. `.config/` holds the real
# pre-commit configuration that `.pre-commit-config.yaml` links to, and the settings of the hooks it runs.
STOP_PREFIXES = (".githooks/", ".pre-commit-config.yaml", ".config/", ".github/workflows/", ".github/actions/", "tools/", "pyproject.toml", "uv.lock")
OUTPUT_TAIL_LINES = 40
NO_HOOKS = ("-c", "core.hooksPath=/dev/null")
# In a check's argv, the commit the worktree is at before the current pull request's first commit: the tip of the pull request
# before it, or the base for the first one applied. That is the state CI's base holds once the pull requests before it have merged.
PULL_BASE = "{pull_base}"

Confirm = Callable[[Sequence[Stop]], bool]


class ReplayError(Exception):
    """The replay stopped at a layer; nothing was pushed."""


@dataclass(frozen=True)
class Check:
    argv: tuple[str, ...]
    cwd: str = "."

    def __str__(self) -> str:
        return " ".join(self.argv)

    def at(self, pull_base: str) -> Check:
        """The check with `PULL_BASE` in its argv replaced by the commit."""
        return Check(tuple(word.replace(PULL_BASE, pull_base) for word in self.argv), self.cwd)


@dataclass(frozen=True)
class TipCheck:
    """A check that runs once, at the last commit of a pull request, and only when CI would run the job behind it.

    `gate` prints `<filter>=true|false` as detect-changes does, for the range from `PULL_BASE` to the pull request's last commit;
    `run` is the job's own command and runs only when the gate says true.
    """

    gate: Check
    run: Check


@dataclass(frozen=True)
class LayerResult:
    layer: Layer
    applied: bool
    commit: str | None = None


def stopped_by(paths: Iterable[str]) -> list[str]:
    """The paths that are on the stop list."""
    return sorted({path for path in paths if path.startswith(STOP_PREFIXES)})


def git_run(repo: Path, *args: str, stdin: bytes | None = None, env: dict[str, str] | None = None, timeout: float | None = None) -> Completed:
    return run(["git", "-C", str(repo), *args], stdin=stdin, env=env, timeout=timeout)


def git_text(result: Completed) -> str:
    return result.output


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


def _am(tree: Path, layer: Layer, onto: str) -> None:
    """`git am` the layer with every hook off: nothing the patch adds runs while it is applied."""
    applied = git_run(tree, *NO_HOOKS, "am", "--quiet", stdin=layer.patch)
    if applied.returncode != 0:
        git_run(tree, "am", "--abort")
        raise ReplayError(f"commit {layer.id} does not apply on {onto}:\n{git_text(applied)}")


def apply_layer(tree: Path, layer: Layer, onto: str) -> list[str]:
    """Apply the layer in `tree` and return every path it changes, read from the commit `git am` makes, so no encoding of the patch hides one."""
    before = git_text(git_run(tree, "rev-parse", "HEAD"))
    _am(tree, layer, onto)
    changed = git_run(tree, "diff", "--no-renames", "--name-only", "-z", before, "HEAD")
    if changed.returncode != 0:
        raise ReplayError(f"cannot read what commit {layer.id} changes: {git_text(changed)}")
    # A name that is not UTF-8 keeps its bytes, so git finds the file again when it is passed back.
    return [path.decode("utf-8", errors="surrogateescape") for path in changed.stdout.split(b"\0") if path]


# What a flagged file's diff is read with: as text whatever the series' attributes call it, and through no external or text conversion driver.
# `--numstat` follows those attributes even so, which is why the lines are counted from the diff.
READABLE_DIFF = ("diff", "--no-renames", "--no-color", "--no-ext-diff", "--no-textconv", "--text")


def _changed_lines(diff: str) -> tuple[int, int]:
    """The added and removed lines of one file's diff: those after its first hunk header that start with `+` or `-`."""
    lines = diff.split("\n")
    start = next((number for number, line in enumerate(lines) if line.startswith("@@")), len(lines))
    return sum(line.startswith("+") for line in lines[start:]), sum(line.startswith("-") for line in lines[start:])


def _read_stop(tree: Path, layer: Layer, paths: Sequence[str]) -> Stop:
    """The line counts and the diff of `paths` in the commit just applied."""
    changes, diffs = [], []
    for path in paths:
        # `:(literal)` stops a file name holding `*` or `[` from being read as a pattern.
        shown = git_run(tree, *READABLE_DIFF, "HEAD^", "HEAD", "--", f":(literal){path}")
        if shown.returncode != 0:
            raise ReplayError(f"cannot read the changes of commit {layer.id}:\n{git_text(shown)}")
        diffs.append(shown.stdout.decode("utf-8", errors="replace"))
        changes.append(Change(path, *_changed_lines(diffs[-1])))
    return Stop(layer, tuple(changes), "".join(diffs))


def _apply_all(tree: Path, layers: Sequence[Layer], base: str) -> list[Stop]:
    """Apply every layer, running nothing, and return those on the stop list; one that does not apply raises here, before any check."""
    stops = []
    for position, layer in enumerate(layers):
        onto = f"{base}{' plus the layers before it' if position else ''}"
        if flagged := stopped_by(apply_layer(tree, layer, onto)):
            stops.append(_read_stop(tree, layer, flagged))
    return stops


LIVE_OUTPUT_LINES = 6


def _gate_is_true(tree: Path, gate: Check, layer: Layer) -> bool:
    """Whether the gate's last output line ends in `=true`; a gate that fails or prints nothing readable stops the replay."""
    try:
        done = subprocess.run(gate.argv, cwd=tree / gate.cwd, capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL, check=False)
    except OSError as error:
        raise ReplayError(f"commit {layer.id}: cannot run `{gate}`: {error}") from error
    lines = done.stdout.strip().splitlines()
    if done.returncode != 0 or not lines or not lines[-1].endswith(("=true", "=false")):
        raise ReplayError(f"commit {layer.id}: cannot tell whether `{gate}` applies:\n{(done.stdout + done.stderr).strip()}")
    return lines[-1].endswith("=true")


def run_check(tree: Path, check: Check, display: Display, label: str) -> str | None:
    """The tail of the output when the check fails, else None. The last lines it prints are shown on the display while it runs and erased when it ends."""
    try:
        process = subprocess.Popen(
            check.argv, cwd=tree / check.cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", stdin=subprocess.DEVNULL
        )
    except OSError as error:
        return f"cannot run it: {error}"
    tail: deque[str] = deque(maxlen=OUTPUT_TAIL_LINES)
    with process:
        try:
            display([label])
            for line in process.stdout or ():
                tail.append(line.rstrip("\r\n"))
                display([label, *(f"  {shown}" for shown in list(tail)[-LIVE_OUTPUT_LINES:])])
        finally:
            display([])
    if process.returncode == 0:
        return None
    return "\n".join(tail).strip()


Progress = Callable[[str], None]


def silent(message: str) -> None:
    """The default progress report: none."""


def preflight(repo: Path) -> list[str]:
    """What the replay needs from this machine and does not find, each with the command or setting that fixes it."""
    problems = []
    if git_run(repo, "var", "GIT_COMMITTER_IDENT").returncode != 0:
        problems.append("git has no committer identity, and `git am` needs one: set user.name and user.email, or GIT_COMMITTER_NAME and GIT_COMMITTER_EMAIL")
    return problems


def _run_tip_check(tree: Path, tip: TipCheck, layer: Layer, pull_base: str, progress: Progress, display: Display) -> None:
    gate, check = tip.gate.at(pull_base), tip.run.at(pull_base)
    if not _gate_is_true(tree, gate, layer):
        progress(f"commit {layer.id}: `{check}` skipped, CI would not run it for this pull request")
        return
    progress(f"commit {layer.id}: running `{check}` on the pull request's last commit")
    failure = run_check(tree, check, display, f"commit {layer.id}: `{check}`")
    if failure is not None:
        raise ReplayError(f"commit {layer.id} fails `{check}`:\n{failure}")


def replay(
    repo: Path,
    layers: Sequence[Layer],
    checks: Sequence[Check],
    confirm: Confirm,
    base: str = "origin/main",
    progress: Progress = silent,
    display: Display = hidden,
    tip_checks: Sequence[TipCheck] = (),
) -> list[LayerResult]:
    """Apply each layer, in the order given, on a scratch worktree of `base`; run every check after each.

    All the layers are first applied with nothing run, and `confirm` is asked once about those on the stop list.

    A check that names `PULL_BASE` sees, for a layer in pull request N, the state pull request N-1 leaves, so it judges
    that pull request's own commits as CI will once the earlier pull requests have merged.

    A tip check runs once per pull request, after the checks of the pull request's last commit, when its gate says CI would run the job.

    Returns what happened to each layer. Raises ReplayError at the first layer that is refused, does not apply or fails a check.
    """
    if problems := preflight(repo):
        raise ReplayError("this machine is not ready to replay:\n" + "\n".join(f"- {problem}" for problem in problems))
    landed = landed_in(repo, base)
    for pull in group_pulls(list(layers)):
        present = [(layer.authored, layer.subject) in landed for layer in pull.layers]
        if any(present) and not all(present):
            raise ReplayError(
                f"pull request {pull.number} is partly in {base}: some of its commits are there and some are not; give the rest a number of their own"
            )
    results: list[LayerResult] = []
    pull_base, current = "", ""
    tips = {layer.number: layer.id for layer in layers}
    with scratch_worktree(repo, base) as tree:
        start = git_text(git_run(tree, "rev-parse", "HEAD"))
        progress("applying every commit before any check runs")
        stops = _apply_all(tree, [layer for layer in layers if (layer.authored, layer.subject) not in landed], base)
        if stops and not confirm(stops):
            named = "; ".join(f"{stop.layer.id} ({', '.join(change.path for change in stop.changes)})" for stop in stops)
            raise ReplayError(f"the series changes code the replay runs and was not confirmed: {named}")
        reset = git_run(tree, *NO_HOOKS, "reset", "--quiet", "--hard", start)
        if reset.returncode != 0:
            raise ReplayError(f"cannot return the worktree to {base}: {git_text(reset)}")
        for layer in layers:
            if (layer.authored, layer.subject) in landed:
                results.append(LayerResult(layer, applied=False))
                continue
            onto = f"{base}{' plus the layers before it' if results else ''}"
            if layer.number != current:
                current, pull_base = layer.number, git_text(git_run(tree, "rev-parse", "HEAD"))
            progress(f"commit {layer.id}: applying the patch on {onto}")
            apply_layer(tree, layer, onto)
            for check in (check.at(pull_base) for check in checks):
                progress(f"commit {layer.id}: running `{check}`")
                failure = run_check(tree, check, display, f"commit {layer.id}: `{check}`")
                if failure is not None:
                    raise ReplayError(f"commit {layer.id} fails `{check}`:\n{failure}")
            if tips[layer.number] == layer.id:
                for tip in tip_checks:
                    _run_tip_check(tree, tip, layer, pull_base, progress, display)
            results.append(LayerResult(layer, applied=True, commit=git_text(git_run(tree, "rev-parse", "HEAD"))))
    return results
