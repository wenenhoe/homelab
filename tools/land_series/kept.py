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


def _record_path(repo: Path, layer: Layer) -> Path:
    common = git_text(git_run(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    return Path(common) / RECORDS_DIR / f"{layer.slug}.json"


def _recorded(repo: Path, layer: Layer) -> dict[str, str] | None:
    path = _record_path(repo, layer)
    return json.loads(path.read_text()) if path.exists() else None


def _tip(repo: Path, layer: Layer) -> str | None:
    result = git_run(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch_of(layer)}")
    return git_text(result) if result.returncode == 0 else None


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


def forget(repo: Path, layer: Layer) -> None:
    """Delete a merged layer's branch and record; a branch that is checked out stays, and the record goes either way."""
    git_run(repo, "branch", "--delete", "--force", branch_of(layer))
    _record_path(repo, layer).unlink(missing_ok=True)
