"""Land a replayed series: for each layer a branch fresh from the base, a pull request, green checks, the maintainer's review, the merge.

The caller replays the series first (`replay.replay`), so nothing here runs before the whole series is known to apply and
pass the local checks. Layers go one at a time: after each merge the base is fetched, so the next branch holds only its own commit.

Every step goes through `git` and `gh` under the maintainer's own login. Only `refs/heads/<slug>` is ever pushed.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from land_series.manifest import RESERVED_SLUGS, Layer
from land_series.replay import ReplayError, apply_layer, git_run, git_text, landed_in, scratch_worktree

CHECKS_INTERVAL_SECONDS = 20
NO_CHECKS_WAIT_SECONDS = 10
NO_CHECKS_RETRIES = 12
OUTPUT_TAIL_LINES = 40

Review = Callable[[Layer, str], bool]


@dataclass(frozen=True)
class Landed:
    layer: Layer
    url: str
    merged: bool


class LandError(Exception):
    """Landing stopped at a layer; the layers in `landed` are merged, and this one's pull request (if any) is left open."""

    def __init__(self, message: str, landed: Sequence[Landed] = ()) -> None:
        super().__init__(message)
        self.landed = list(landed)


def fetch(repo: Path, base: str) -> None:
    remote, _, branch = base.partition("/")
    result = subprocess.run(["git", "-C", str(repo), "fetch", "--quiet", remote, branch], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise ReplayError(f"cannot fetch {base}: {result.stderr.strip()}")


def _gh(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["gh", *args], cwd=repo, capture_output=True, text=True, check=False)


def _gh_ok(repo: Path, *args: str) -> str:
    result = _gh(repo, *args)
    if result.returncode != 0:
        raise LandError(f"`gh {' '.join(args[:2])}` failed: {(result.stdout + result.stderr).strip()}")
    return result.stdout.strip()


def _rev(tree: Path, rev: str) -> str:
    result = git_run(tree, "rev-parse", "--verify", "--quiet", rev)
    return result.stdout.decode().strip() if result.returncode == 0 else ""


def _publish(repo: Path, layer: Layer, base: str) -> tuple[str, bool]:
    """Apply the layer on a fresh worktree of the base and push it as its branch; return the commit's message body and whether the push changed anything.

    A branch already on the remote with the same tree on the same parent is the same patch, and is left alone.
    """
    remote, _, _ = base.partition("/")
    ref = f"refs/heads/{layer.slug}"
    with scratch_worktree(repo, base) as tree:
        apply_layer(tree, layer, base)
        listed = git_run(tree, "ls-remote", remote, ref)
        if listed.returncode != 0:
            raise LandError(f"cannot list {ref} on {remote}: {git_text(listed)}")
        existing = listed.stdout.decode().split("\t")[0]
        if existing:
            git_run(tree, "fetch", "--quiet", remote, ref)
            if (_rev(tree, "FETCH_HEAD^{tree}"), _rev(tree, "FETCH_HEAD^")) == (_rev(tree, "HEAD^{tree}"), _rev(tree, "HEAD^")):
                return git_run(tree, "log", "-1", "--format=%b").stdout.decode().strip(), False
        pushed = git_run(tree, "push", "--quiet", f"--force-with-lease={ref}:{existing}", remote, f"HEAD:{ref}")
        if pushed.returncode != 0:
            raise LandError(f"cannot push {ref}: {git_text(pushed)}")
        return git_run(tree, "log", "-1", "--format=%b").stdout.decode().strip(), True


def _pull_request(repo: Path, layer: Layer, branch: str, body: str, changed: bool) -> str:
    """The address of the layer's open pull request into `branch`: created, or updated when the patch changed."""
    listed = json.loads(_gh_ok(repo, "pr", "list", "--head", layer.slug, "--base", branch, "--state", "open", "--json", "number,url") or "[]")
    if listed:
        if changed:
            _gh_ok(repo, "pr", "edit", str(listed[0]["number"]), "--title", layer.subject, "--body", body)
        return listed[0]["url"]
    return _gh_ok(repo, "pr", "create", "--base", branch, "--head", layer.slug, "--title", layer.subject, "--body", body).splitlines()[-1]


def _wait_for_checks(repo: Path, url: str, sleep: Callable[[float], None]) -> None:
    for _ in range(NO_CHECKS_RETRIES + 1):
        result = _gh(repo, "pr", "checks", url, "--watch", "--interval", str(CHECKS_INTERVAL_SECONDS), "--required")
        if result.returncode == 0:
            return
        output = (result.stdout + result.stderr).strip()
        if "checks reported" not in output:
            tail = "\n".join(output.splitlines()[-OUTPUT_TAIL_LINES:])
            raise LandError(f"the required checks on {url} did not pass:\n{tail}")
        sleep(NO_CHECKS_WAIT_SECONDS)
    raise LandError(f"no required checks reported on {url} after waiting")


def land(repo: Path, layers: Sequence[Layer], review: Review, base: str = "origin/main", sleep: Callable[[float], None] = time.sleep) -> list[Landed]:
    """Land the layers in the order given; stop, with its pull request left open, at the first one the maintainer does not confirm."""
    _, _, branch = base.partition("/")
    results: list[Landed] = []
    fetch(repo, base)
    try:
        _land_each(repo, layers, review, base, branch, sleep, results)
    except LandError as error:
        error.landed = results
        raise
    except ReplayError as error:
        raise LandError(str(error), results) from error
    return results


def _land_each(repo: Path, layers: Sequence[Layer], review: Review, base: str, branch: str, sleep: Callable[[float], None], results: list[Landed]) -> None:
    for layer in layers:
        if layer.slug in RESERVED_SLUGS:
            raise LandError(f"layer {layer.id} has the protected branch name {layer.slug!r}")
        if (layer.authored, layer.subject) in landed_in(repo, base):
            continue
        body, changed = _publish(repo, layer, base)
        url = _pull_request(repo, layer, branch, body, changed)
        _wait_for_checks(repo, url, sleep)
        if not review(layer, url):
            results.append(Landed(layer, url, merged=False))
            break
        _gh_ok(repo, "pr", "merge", url, "--admin", "--merge", "--delete-branch")
        fetch(repo, base)
        results.append(Landed(layer, url, merged=True))
