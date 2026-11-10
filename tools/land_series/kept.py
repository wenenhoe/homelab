"""The local branches a replay leaves for review, and the record that shows they are still as the tool built them.

`series/<slug>` is a chain: each layer's commit sits on the one before it, and the first on the base. A record beside the
repository's git directory holds the commit the tool built and a hash of the patch it came from, so landing pushes a branch only
while its tip is that commit and the patch is the one in the series file. The branch is never compared with a rebuild: the generated
views carry dates of the apply, so a rebuilt commit differs from the kept one in content nobody changed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

from land_series.manifest import Layer
from land_series.replay import LayerResult, git_run, git_text

BRANCH_PREFIX = "series/"
RECORDS_DIR = "land-series"


class KeptError(Exception):
    """A kept branch is missing, was not left by this tool, or has changed since."""


def branch_of(layer: Layer) -> str:
    return f"{BRANCH_PREFIX}{layer.slug}"


def _records_dir(repo: Path) -> Path:
    return Path(git_text(git_run(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))) / RECORDS_DIR


def _record_path(repo: Path, layer: Layer) -> Path:
    return _records_dir(repo) / f"{layer.slug}.json"


def _recorded(repo: Path, layer: Layer) -> dict[str, str] | None:
    path = _record_path(repo, layer)
    return json.loads(path.read_text()) if path.exists() else None


def _branch_tip(repo: Path, branch: str) -> str | None:
    result = git_run(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
    return git_text(result) if result.returncode == 0 else None


def _tip(repo: Path, layer: Layer) -> str | None:
    return _branch_tip(repo, branch_of(layer))


def _patch_hash(layer: Layer) -> str:
    return hashlib.sha256(layer.patch).hexdigest()


def keep(repo: Path, results: Sequence[LayerResult]) -> list[str]:
    """Leave a branch for each layer the replay applied, replacing one this tool left earlier; return the branch names.

    Refuses, before changing anything, a branch that exists but is not one this tool left unchanged.
    """
    built = [result for result in results if result.applied and result.commit]
    for result in built:
        tip, record = _tip(repo, result.layer), _recorded(repo, result.layer)
        if tip is not None and (record is None or record["tip"] != tip):
            raise KeptError(f"{branch_of(result.layer)} exists and is not as this tool left it; delete or rename it, or land from it as it is")
    names = []
    for result in built:
        created = git_run(repo, "branch", "--force", branch_of(result.layer), result.commit or "")
        if created.returncode != 0:
            raise KeptError(f"cannot update {branch_of(result.layer)}: {git_text(created)}")
        path = _record_path(repo, result.layer)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"tip": result.commit, "patch": _patch_hash(result.layer)}))
        names.append(branch_of(result.layer))
    return names


def kept_tip(repo: Path, layer: Layer) -> str:
    """The commit of the layer's kept branch, if the branch is still exactly what the tool built from this layer's patch."""
    tip = _tip(repo, layer)
    if tip is None:
        raise KeptError(f"layer {layer.id} has no {branch_of(layer)}; run without --land first to build and review it")
    record = _recorded(repo, layer)
    if record is None or record["tip"] != tip:
        raise KeptError(f"{branch_of(layer)} has changed since the tool built it; delete it and run without --land to rebuild it from its patch")
    if record["patch"] != _patch_hash(layer):
        raise KeptError(f"{branch_of(layer)} was built from a different patch than layer {layer.id} now has; run without --land to rebuild it")
    return tip


def is_ready(repo: Path, tip: str, base: str) -> bool:
    """Whether `base` holds exactly the tree the commit was built on, so it applies to `base` as built and the views are still right."""
    built_on = git_run(repo, "rev-parse", "--verify", "--quiet", f"{tip}^1^{{tree}}")
    current = git_run(repo, "rev-parse", "--verify", "--quiet", f"{base}^{{tree}}")
    return built_on.returncode == 0 and current.returncode == 0 and git_text(built_on) == git_text(current)


def rebase(repo: Path, layer: Layer, tip: str, base: str) -> str:
    """Move the kept commit onto `base`'s current commit, and return it; the commit itself when it is already there.

    Only valid once `is_ready` holds: `base` has the tree the commit was built on, so the new commit has the very
    tree that was reviewed and author, committer, dates and message carry over. Its parent is the commit the
    previous layer's merge left on `base`, so the layers land on one line instead of a chain of side branches.
    """
    base_commit = git_text(git_run(repo, "rev-parse", f"{base}^{{commit}}"))
    if git_text(git_run(repo, "rev-parse", f"{tip}^1")) == base_commit:
        return tip
    who = git_text(git_run(repo, "log", "-1", "--format=%an%n%ae%n%aI%n%cn%n%ce%n%cI", tip)).split("\n")
    names = ("AUTHOR_NAME", "AUTHOR_EMAIL", "AUTHOR_DATE", "COMMITTER_NAME", "COMMITTER_EMAIL", "COMMITTER_DATE")
    message = git_run(repo, "log", "-1", "--format=%B", tip).stdout
    made = git_run(
        repo, "commit-tree", f"{tip}^{{tree}}", "-p", base_commit, stdin=message, env={f"GIT_{name}": value for name, value in zip(names, who, strict=True)}
    )
    if made.returncode != 0:
        raise KeptError(f"cannot move {branch_of(layer)} onto {base}: {git_text(made)}")
    new = git_text(made)
    moved = git_run(repo, "update-ref", f"refs/heads/{branch_of(layer)}", new, tip)
    if moved.returncode != 0:
        raise KeptError(f"cannot move {branch_of(layer)} onto {base}: {git_text(moved)}")
    _record_path(repo, layer).write_text(json.dumps({"tip": new, "patch": _patch_hash(layer)}))
    return new


def forget(repo: Path, layer: Layer) -> bool:
    """Delete a merged layer's branch and record. The record goes either way; a branch that is checked out stays, and False says so."""
    deleted = git_run(repo, "branch", "--delete", "--force", branch_of(layer)).returncode == 0
    _record_path(repo, layer).unlink(missing_ok=True)
    return deleted or _branch_tip(repo, branch_of(layer)) is None


def leftovers(repo: Path, active: Sequence[Layer]) -> list[str]:
    """The kept branches the tool left for layers that are not in `active`: dropped from the series, renamed, or already landed.

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
