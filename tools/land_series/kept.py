"""The local branches a replay leaves for review, and the record that shows they are still as the tool built them.

`series/<slug>` is a pull request's branch, and the branches form a chain: a pull request's commits sit on the one before, and
the first on the base. A record beside the repository's git directory holds the first and last commit the tool built and a hash
of the patches they came from, so landing pushes a branch only while its tip is that commit and the patches are the ones in the
series file. The branch is never compared with a rebuild: the generated views carry dates of the apply, so a rebuilt commit
differs from the kept one in content nobody changed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

from land_series.manifest import Layer, Pull, group_pulls
from land_series.replay import LayerResult, git_run, git_text

BRANCH_PREFIX = "series/"
RECORDS_DIR = "land-series"


class KeptError(Exception):
    """A kept branch is missing, was not left by this tool, or has changed since."""


def branch_of(pull: Pull | Layer) -> str:
    return f"{BRANCH_PREFIX}{pull.slug}"


def _records_dir(repo: Path) -> Path:
    return Path(git_text(git_run(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))) / RECORDS_DIR


def _record_path(repo: Path, pull: Pull | Layer) -> Path:
    return _records_dir(repo) / f"{pull.slug}.json"


def _recorded(repo: Path, pull: Pull | Layer) -> dict[str, str] | None:
    path = _record_path(repo, pull)
    return json.loads(path.read_text()) if path.exists() else None


def _branch_tip(repo: Path, branch: str) -> str | None:
    result = git_run(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
    return git_text(result) if result.returncode == 0 else None


def _tip(repo: Path, pull: Pull | Layer) -> str | None:
    return _branch_tip(repo, branch_of(pull))


def _patch_hash(pull: Pull) -> str:
    """One hash for the pull request's patches, in order."""
    return hashlib.sha256(b"".join(hashlib.sha256(layer.patch).digest() for layer in pull.layers)).hexdigest()


def _checked_out(repo: Path) -> set[str]:
    """The branches checked out in this repository or any of its worktrees."""
    listing = git_text(git_run(repo, "worktree", "list", "--porcelain"))
    return {line.removeprefix("branch refs/heads/") for line in listing.splitlines() if line.startswith("branch refs/heads/")}


def _built(results: Sequence[LayerResult]) -> list[tuple[Pull, str, str]]:
    """For each pull request the replay applied: it, its first commit and its last."""
    built = []
    for pull in group_pulls([result.layer for result in results if result.applied]):
        commits = {result.layer.id: result.commit for result in results if result.applied and result.layer.number == pull.number}
        built.append((pull, commits[pull.layers[0].id] or "", commits[pull.layers[-1].id] or ""))
    return built


def keep(repo: Path, results: Sequence[LayerResult]) -> list[str]:
    """Leave a branch for each pull request the replay applied, replacing one this tool left earlier; return the branch names.

    Refuses, before changing anything, a branch that exists but is not one this tool left unchanged, and one that is checked out.
    """
    built = _built(results)
    for pull, _, _ in built:
        tip, record = _tip(repo, pull), _recorded(repo, pull)
        if tip is not None and (record is None or record["tip"] != tip):
            raise KeptError(f"{branch_of(pull)} exists and is not as this tool left it; delete or rename it, or land from it as it is")
    checked_out = _checked_out(repo)
    for pull, _, _ in built:
        if branch_of(pull) in checked_out:
            raise KeptError(f"{branch_of(pull)} is checked out; switch to another branch (`git switch main`), then run again so it can be rebuilt")
    names = []
    for pull, first, last in built:
        created = git_run(repo, "branch", "--force", branch_of(pull), last)
        if created.returncode != 0:
            raise KeptError(f"cannot update {branch_of(pull)}: {git_text(created)}")
        path = _record_path(repo, pull)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"first": first, "tip": last, "patch": _patch_hash(pull)}))
        names.append(branch_of(pull))
    return names


def kept_tip(repo: Path, pull: Pull) -> tuple[str, str]:
    """The first and last commit of the pull request's kept branch, if the branch is still exactly what the tool built from its patches."""
    tip = _tip(repo, pull)
    if tip is None:
        raise KeptError(f"pull request {pull.number} has no {branch_of(pull)}; run without --land first to build and review it")
    record = _recorded(repo, pull)
    if record is None or record["tip"] != tip:
        raise KeptError(f"{branch_of(pull)} has changed since the tool built it; delete it and run without --land to rebuild it from its patches")
    if "first" not in record:
        raise KeptError(f"{branch_of(pull)} was kept by an older version of this tool; run without --land to rebuild it")
    if record["patch"] != _patch_hash(pull):
        raise KeptError(f"{branch_of(pull)} was built from different patches than pull request {pull.number} now has; run without --land to rebuild it")
    return record["first"], tip


def is_ready(repo: Path, first: str, base: str) -> bool:
    """Whether `base` holds exactly the tree the first commit was built on, so the commits apply to `base` as built and the views are still right."""
    built_on = git_run(repo, "rev-parse", "--verify", "--quiet", f"{first}^1^{{tree}}")
    current = git_run(repo, "rev-parse", "--verify", "--quiet", f"{base}^{{tree}}")
    return built_on.returncode == 0 and current.returncode == 0 and git_text(built_on) == git_text(current)


def rebase(repo: Path, pull: Pull, first: str, tip: str, base: str) -> tuple[str, str]:
    """Move the kept commits onto `base`'s current commit, and return the new first and last; the same ones when already there.

    Only valid once `is_ready` holds: `base` has the tree the first commit was built on, so every new commit has the very
    tree that was reviewed and author, committer, dates and message carry over. The first one's parent is the commit the
    previous pull request's merge left on `base`, so the pull requests land on one line instead of a chain of side branches.
    """
    base_commit = git_text(git_run(repo, "rev-parse", f"{base}^{{commit}}"))
    if git_text(git_run(repo, "rev-parse", f"{first}^1")) == base_commit:
        return first, tip
    names = ("AUTHOR_NAME", "AUTHOR_EMAIL", "AUTHOR_DATE", "COMMITTER_NAME", "COMMITTER_EMAIL", "COMMITTER_DATE")
    commits = git_text(git_run(repo, "rev-list", "--reverse", f"{first}^1..{tip}")).split()
    parent, new_first = base_commit, ""
    for commit in commits:
        who = git_text(git_run(repo, "log", "-1", "--format=%an%n%ae%n%aI%n%cn%n%ce%n%cI", commit)).split("\n")
        message = git_run(repo, "log", "-1", "--format=%B", commit).stdout
        made = git_run(
            repo, "commit-tree", f"{commit}^{{tree}}", "-p", parent, stdin=message, env={f"GIT_{name}": value for name, value in zip(names, who, strict=True)}
        )
        if made.returncode != 0:
            raise KeptError(f"cannot move {branch_of(pull)} onto {base}: {git_text(made)}")
        parent = git_text(made)
        new_first = new_first or parent
    moved = git_run(repo, "update-ref", f"refs/heads/{branch_of(pull)}", parent, tip)
    if moved.returncode != 0:
        raise KeptError(f"cannot move {branch_of(pull)} onto {base}: {git_text(moved)}")
    _record_path(repo, pull).write_text(json.dumps({"first": new_first, "tip": parent, "patch": _patch_hash(pull)}))
    return new_first, parent


def forget(repo: Path, pull: Pull) -> bool:
    """Delete a merged pull request's branch and record. The record goes either way; a branch that is checked out stays, and False says so."""
    deleted = git_run(repo, "branch", "--delete", "--force", branch_of(pull)).returncode == 0
    _record_path(repo, pull).unlink(missing_ok=True)
    return deleted or _branch_tip(repo, branch_of(pull)) is None


def leftovers(repo: Path, active: Sequence[Layer]) -> list[str]:
    """The kept branches the tool left for pull requests that are not in `active`: dropped from the series, renamed, or already landed.

    A record whose branch is gone is deleted here, so a branch removed by hand is not reported again.
    """
    wanted = {layer.slug for layer in active}
    found = []
    for path in sorted(_records_dir(repo).glob("*.json")):
        if path.stem in wanted:
            continue
        branch = f"{BRANCH_PREFIX}{path.stem}"
        if _branch_tip(repo, branch) is None:
            path.unlink()
        else:
            found.append(branch)
    return found
