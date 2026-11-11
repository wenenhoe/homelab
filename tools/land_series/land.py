"""Land a kept series: for each pull request its branch pushed as built, a pull request, green checks, the maintainer's review, the merge.

The branches come from a replay (`replay.replay` then `kept.keep`), so nothing here runs before the whole series is known to
apply and pass the local checks, and a branch is pushed only while it is exactly what the tool built. Pull requests go one at a time:
a pull request's first commit sits on the last of the one before it, which a merge commit has brought into the base, so its pull
request shows only its own commits.

Every step goes through `git` and `gh` under the maintainer's own login. Only `refs/heads/<slug>` is ever pushed.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from land_series.kept import KeptError, branch_of, forget, is_ready, kept_tip, rebase
from land_series.live import Display, check_lines, hidden
from land_series.manifest import RESERVED_SLUGS, Layer, Pull, group_pulls
from land_series.replay import Progress, ReplayError, git_run, git_text, landed_in, silent

CHECKS_INTERVAL_SECONDS = 20
CHECKS_MAX_POLLS = 270  # about 90 minutes at the interval above
PASSING_BUCKETS = frozenset({"pass", "skipping"})
FAILING_BUCKETS = frozenset({"fail", "cancel"})

Review = Callable[[Pull, str], bool]


@dataclass(frozen=True)
class Landed:
    pull: Pull
    url: str
    merged: bool
    kept_branch: str | None = None  # set when the merged pull request's local branch could not be deleted, because it is checked out


class LandError(Exception):
    """Landing stopped at a pull request; those in `landed` are merged, and this one's (if any) is left open."""

    def __init__(self, message: str, landed: Sequence[Landed] = ()) -> None:
        super().__init__(message)
        self.landed = list(landed)


FETCH_ATTEMPTS = 3
FETCH_RETRY_SECONDS = 2.0


def fetch(repo: Path, base: str, sleep: Callable[[float], None] = time.sleep) -> None:
    """Bring `base` up to date. A client fetching in the background can update the same ref at the same moment and fail this fetch once, so it is retried."""
    remote, _, branch = base.partition("/")
    for attempt in range(FETCH_ATTEMPTS):
        result = subprocess.run(["git", "-C", str(repo), "fetch", "--quiet", remote, branch], capture_output=True, text=True, check=False)
        if result.returncode == 0:
            return
        if attempt < FETCH_ATTEMPTS - 1:
            sleep(FETCH_RETRY_SECONDS)
    raise ReplayError(f"cannot fetch {base}: {result.stderr.strip()}")


def _gh(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["gh", *args], cwd=repo, capture_output=True, text=True, check=False)


def _gh_ok(repo: Path, *args: str) -> str:
    result = _gh(repo, *args)
    if result.returncode != 0:
        raise LandError(f"`gh {' '.join(args[:2])}` failed: {(result.stdout + result.stderr).strip()}")
    return result.stdout.strip()


def _body(repo: Path, pull: Pull, tip: str) -> str:
    """A single commit's message body, or for several commits their subjects."""
    if len(pull.layers) > 1:
        return "\n".join(f"- {layer.subject}" for layer in pull.layers)
    return git_run(repo, "log", "-1", "--format=%b", tip).stdout.decode().strip()


def _push(repo: Path, pull: Pull, tip: str, base: str) -> tuple[str, bool]:
    """Push the kept commits as the pull request's branch; return the pull request body and whether the remote branch changed.

    A remote branch already at that commit is left alone.
    """
    remote, _, _ = base.partition("/")
    ref = f"refs/heads/{pull.slug}"
    listed = git_run(repo, "ls-remote", remote, ref)
    if listed.returncode != 0:
        raise LandError(f"cannot list {ref} on {remote}: {git_text(listed)}")
    existing = listed.stdout.decode().split("\t")[0]
    body = _body(repo, pull, tip)
    if existing == tip:
        return body, False
    pushed = git_run(repo, "push", "--quiet", f"--force-with-lease={ref}:{existing}", remote, f"{tip}:{ref}")
    if pushed.returncode != 0:
        raise LandError(f"cannot push {ref}: {git_text(pushed)}")
    return body, True


def _pull_request(repo: Path, pull: Pull, branch: str, body: str, changed: bool) -> str:
    """The address of the open pull request into `branch`: created, or updated when its commits changed.

    `gh pr list --head` takes a bare branch name, so a pull request from a fork's branch of the same name is listed too; only one
    whose head branch is in this repository can be the one the tool opened.
    """
    found = json.loads(_gh_ok(repo, "pr", "list", "--head", pull.slug, "--base", branch, "--state", "open", "--json", "number,url,isCrossRepository") or "[]")
    listed = [candidate for candidate in found if not candidate["isCrossRepository"]]
    if listed:
        if changed:
            _gh_ok(repo, "pr", "edit", str(listed[0]["number"]), "--title", pull.title, "--body", body)
        return listed[0]["url"]
    return _gh_ok(repo, "pr", "create", "--base", branch, "--head", pull.slug, "--title", pull.title, "--body", body).splitlines()[-1]


def required_checks(repo: Path, branch: str) -> frozenset[str]:
    """The names of the status checks the rulesets require on `branch`, read once per run, before the first push, and never cached on disk.

    `gh pr checks --required` lists only checks GitHub has already reported, and a job with `needs` (`matrix-jobs-gate`) is not
    reported until what it needs has finished, so the pull request's own list cannot say what is still to come.
    """
    rules = json.loads(_gh_ok(repo, "api", f"repos/{{owner}}/{{repo}}/rules/branches/{branch}") or "[]")
    names = frozenset(
        check["context"] for rule in rules if rule.get("type") == "required_status_checks" for check in rule["parameters"]["required_status_checks"]
    )
    if not names:
        raise LandError(f"the rulesets list no required status checks for {branch}, so there is nothing to wait for before a merge")
    return names


def _reported(repo: Path, url: str) -> dict[str, set[str]]:
    """Each check name the pull request has so far, with the buckets it is in. `gh` exits 8 while checks are pending, so the exit code is not read."""
    result = _gh(repo, "pr", "checks", url, "--json", "name,bucket")
    try:
        return _buckets(json.loads(result.stdout))
    except json.JSONDecodeError:
        output = (result.stdout + result.stderr).strip()
        if "checks reported" in output:
            return {}
        raise LandError(f"`gh pr checks` failed on {url}: {output}") from None


def _buckets(checks: Sequence[dict[str, str]]) -> dict[str, set[str]]:
    buckets: dict[str, set[str]] = {}
    for check in checks:
        buckets.setdefault(check["name"], set()).add(check["bucket"])
    return buckets


def _wait_for_checks(repo: Path, url: str, required: frozenset[str], sleep: Callable[[float], None], display: Display, label: str) -> None:
    """Return once every required check is reported and passing; raise at the first that failed, or when they are still not all in after the limit.

    The block on the display lists what has not passed yet and is erased on every way out.
    """
    names = sorted(required)
    waiting: list[str] = []
    try:
        for poll in range(CHECKS_MAX_POLLS):
            if poll:
                sleep(CHECKS_INTERVAL_SECONDS)
            reported = _reported(repo, url)
            failed = [name for name in names if reported.get(name, set()) & FAILING_BUCKETS]
            if failed:
                raise LandError(
                    f"the required checks on {url} did not pass:\n" + "\n".join(f"{name}  {min(reported[name] & FAILING_BUCKETS)}" for name in failed)
                )
            waiting = [name for name in names if not reported.get(name) or not reported[name] <= PASSING_BUCKETS]
            if not waiting:
                return
            display(check_lines(label, names, reported))
    finally:
        display([])
    minutes = CHECKS_MAX_POLLS * CHECKS_INTERVAL_SECONDS // 60
    raise LandError(f"the required checks on {url} were not all passing after {minutes} minutes; still waiting for: {', '.join(waiting)}")


def _moved(repo: Path, pull: Pull, first: str, tip: str, base: str) -> str:
    """Why a pull request cannot land as built: `base` holds more than it was built on. Says whether its change would still apply."""
    merged = git_run(repo, "merge-tree", "--write-tree", f"--merge-base={first}^1", base, tip)
    verdict = "its change now conflicts with it" if merged.returncode == 1 else "its change still applies, but no check has run on the result"
    return f"{base} has changed since pull request {pull.number} was built, and {verdict}; run without --land to rebuild the series, review it, then land it"


def land(
    repo: Path,
    layers: Sequence[Layer],
    review: Review,
    base: str = "origin/main",
    sleep: Callable[[float], None] = time.sleep,
    progress: Progress = silent,
    display: Display = hidden,
) -> list[Landed]:
    """Land the pull requests in the order given; stop, with its pull request left open, at the first one the maintainer does not confirm."""
    _, _, branch = base.partition("/")
    results: list[Landed] = []
    fetch(repo, base)
    try:
        _land_each(repo, layers, review, base, branch, cache(lambda: required_checks(repo, branch)), sleep, results, progress, display)
    except LandError as error:
        error.landed = results
        raise
    except ReplayError as error:
        raise LandError(str(error), results) from error
    return results


def _land_each(
    repo: Path,
    layers: Sequence[Layer],
    review: Review,
    base: str,
    branch: str,
    required: Callable[[], frozenset[str]],
    sleep: Callable[[float], None],
    results: list[Landed],
    progress: Progress,
    display: Display,
) -> None:
    for pull in group_pulls(list(layers)):
        label = f"pull request {pull.number}"
        if pull.slug in RESERVED_SLUGS:
            raise LandError(f"{label} has the protected branch name {pull.slug!r}")
        landed = landed_in(repo, base)
        present = [(layer.authored, layer.subject) in landed for layer in pull.layers]
        if all(present):
            continue
        if any(present):
            raise LandError(f"{label} is partly in {base}: some of its commits are there and some are not; give the rest a number of their own")
        try:
            first, tip = kept_tip(repo, pull)
        except KeptError as error:
            raise LandError(str(error)) from error
        if not is_ready(repo, first, base):
            raise LandError(_moved(repo, pull, first, tip, base))
        try:
            first, tip = rebase(repo, pull, first, tip, base)
        except KeptError as error:
            raise LandError(str(error)) from error
        wanted = required()
        progress(f"{label}: pushing {pull.slug}")
        body, changed = _push(repo, pull, tip, base)
        progress(f"{label}: opening or updating its pull request into {branch}")
        url = _pull_request(repo, pull, branch, body, changed)
        progress(f"{label}: waiting for the required checks on {url} (this is CI, it can take several minutes)")
        _wait_for_checks(repo, url, wanted, sleep, display, label)
        progress(f"{label}: all {len(wanted)} required checks passed")
        if not review(pull, url):
            results.append(Landed(pull, url, merged=False))
            break
        progress(f"{label}: merging")
        _gh_ok(repo, "pr", "merge", url, "--admin", "--merge", "--delete-branch", "--match-head-commit", tip)
        deleted = forget(repo, pull)
        results.append(Landed(pull, url, merged=True, kept_branch=None if deleted else branch_of(pull)))
        fetch(repo, base, sleep)
