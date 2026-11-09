"""Land a kept series: for each layer its branch pushed as built, a pull request, green checks, the maintainer's review, the merge.

The branches come from a replay (`replay.replay` then `kept.keep`), so nothing here runs before the whole series is known to
apply and pass the local checks, and a branch is pushed only while it is exactly what the tool built. Layers go one at a time:
a layer's commit sits on the one before it, which a merge commit has brought into the base, so its pull request shows only its own commit.

Every step goes through `git` and `gh` under the maintainer's own login. Only `refs/heads/<slug>` is ever pushed.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from land_series.kept import KeptError, forget, is_ready, kept_tip
from land_series.manifest import RESERVED_SLUGS, Layer
from land_series.replay import ReplayError, git_run, git_text, landed_in

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


def _push(repo: Path, layer: Layer, tip: str, base: str) -> tuple[str, bool]:
    """Push the kept commit as the layer's branch; return its message body and whether the remote branch changed.

    A remote branch already at that commit is left alone.
    """
    remote, _, _ = base.partition("/")
    ref = f"refs/heads/{layer.slug}"
    listed = git_run(repo, "ls-remote", remote, ref)
    if listed.returncode != 0:
        raise LandError(f"cannot list {ref} on {remote}: {git_text(listed)}")
    existing = listed.stdout.decode().split("\t")[0]
    body = git_run(repo, "log", "-1", "--format=%b", tip).stdout.decode().strip()
    if existing == tip:
        return body, False
    pushed = git_run(repo, "push", "--quiet", f"--force-with-lease={ref}:{existing}", remote, f"{tip}:{ref}")
    if pushed.returncode != 0:
        raise LandError(f"cannot push {ref}: {git_text(pushed)}")
    return body, True


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
        try:
            tip = kept_tip(repo, layer)
        except KeptError as error:
            raise LandError(str(error)) from error
        if not is_ready(repo, tip, base):
            raise LandError(f"{base} has changed since layer {layer.id} was built; run without --land to rebuild the series, review it, then land it")
        body, changed = _push(repo, layer, tip, base)
        url = _pull_request(repo, layer, branch, body, changed)
        _wait_for_checks(repo, url, sleep)
        if not review(layer, url):
            results.append(Landed(layer, url, merged=False))
            break
        _gh_ok(repo, "pr", "merge", url, "--admin", "--merge", "--delete-branch")
        forget(repo, layer)
        fetch(repo, base)
        results.append(Landed(layer, url, merged=True))
