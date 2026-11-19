"""Merge the pull requests a summary was read for, each only at the commit that was read.

A pull request goes in when it is still open on the summary's branch, its head is the commit the summary recorded, and every check the
rulesets require on the branch has passed. Renovate force-pushes a branch when it updates it, so a head that has moved means notes
nobody read. Nothing here uses the admin bypass: a pull request the rulesets would refuse stays open with GitHub's reason.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from land_series.land import CHECKS_INTERVAL_SECONDS, CHECKS_MAX_POLLS, FAILING_BUCKETS, PASSING_BUCKETS, LandError, required_checks
from land_series.run import CommandError, run

from renovate_merge import gh
from renovate_merge.flags import LEVEL_NONE

PROTECTED_BRANCHES = frozenset({"main"})

Progress = Callable[[str], None]
Confirm = Callable[[Sequence["Reviewed"]], bool]


class MergeError(Exception):
    """The run stopped before any pull request was merged."""


@dataclass(frozen=True)
class Reviewed:
    number: int
    title: str
    url: str
    head_sha: str
    level: str


@dataclass(frozen=True)
class Summary:
    base: str
    pulls: dict[int, Reviewed]


@dataclass(frozen=True)
class Outcome:
    number: int
    url: str
    merged: bool
    reason: str = ""


def silent(message: str) -> None:
    """The default progress: none."""


def load_summary(text: str) -> Summary:
    """The summary file the `summary` command wrote; anything else is refused, since what it names gets merged."""
    try:
        record = json.loads(text)
        base = record["base"]
        pulls = {item["number"]: Reviewed(item["number"], item["title"], item["url"], item["head_sha"], item["level"]) for item in record["pulls"]}
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise MergeError(f"not a summary written by `renovate_merge summary`: {error!r}") from error
    if not isinstance(base, str) or not all(isinstance(number, int) for number in pulls):
        raise MergeError("not a summary written by `renovate_merge summary`: the branch or a pull request number has the wrong type")
    if base in PROTECTED_BRANCHES:
        raise MergeError(f"this tool never merges into {base}: a merge there is a deploy")
    return Summary(base, pulls)


def select(summary: Summary, numbers: Sequence[int]) -> list[Reviewed]:
    """The pull requests named, which are merged whatever their level, or with none named every one at level `none`."""
    if not numbers:
        return [pull for _, pull in sorted(summary.pulls.items()) if pull.level == LEVEL_NONE]
    unknown = [number for number in numbers if number not in summary.pulls]
    if unknown:
        raise MergeError(f"not in the summary: {', '.join(f'#{number}' for number in unknown)}; run `summary` again")
    return [summary.pulls[number] for number in sorted(set(numbers))]


class ChecksUnreadable(Exception):
    """`gh pr checks` printed something that is neither a list of checks nor the notice that none are reported yet."""


def _reported(repo: Path, number: int) -> dict[str, set[str]]:
    """Each check name the pull request has so far, with its buckets. `gh` exits 8 while checks are pending, so the exit code is not read."""
    result = run(["gh", "pr", "checks", str(number), "--json", "name,bucket"], cwd=repo, timeout=gh.GH_TIMEOUT_SECONDS)
    try:
        listed = json.loads(result.stdout)
    except json.JSONDecodeError:
        if "checks reported" in result.output:
            return {}
        raise ChecksUnreadable(result.output) from None
    buckets: dict[str, set[str]] = {}
    for check in listed:
        buckets.setdefault(check["name"], set()).add(check["bucket"])
    return buckets


def _check_state(reported: dict[str, set[str]], required: frozenset[str]) -> tuple[list[str], list[str]]:
    """The required checks that failed, and those not yet passing."""
    failed = sorted(name for name in required if reported.get(name, set()) & FAILING_BUCKETS)
    waiting = sorted(name for name in required if not reported.get(name) or not reported[name] <= PASSING_BUCKETS)
    return failed, waiting


def wait_for_checks(repo: Path, number: int, required: frozenset[str], sleep: Callable[[float], None]) -> str:
    """An empty string once every required check has passed, otherwise why the pull request cannot be merged."""
    waiting: list[str] = []
    for poll in range(CHECKS_MAX_POLLS):
        if poll:
            sleep(CHECKS_INTERVAL_SECONDS)
        try:
            failed, waiting = _check_state(_reported(repo, number), required)
        except (CommandError, ChecksUnreadable) as error:
            return f"reading its checks failed: {' '.join(str(error).split())}"
        if failed:
            return f"required checks failed: {', '.join(failed)}"
        if not waiting:
            return ""
    return f"required checks still not passing after {CHECKS_MAX_POLLS * CHECKS_INTERVAL_SECONDS // 60} minutes: {', '.join(waiting)}"


def _refusal(view: dict, pull: Reviewed, base: str) -> str:
    """Why the pull request is not what the summary describes, or an empty string."""
    if view["state"] != "OPEN":
        return f"it is {view['state'].lower()}"
    if view["baseRefName"] != base:
        return f"it now targets {view['baseRefName']}, not {base}"
    if view["headRefOid"] != pull.head_sha:
        return f"its head moved from {pull.head_sha[:7]} to {view['headRefOid'][:7]} since the summary was read; run `summary` again"
    return ""


def _merge_one(repo: Path, pull: Reviewed, base: str, required: frozenset[str], dry_run: bool, sleep: Callable[[float], None], progress: Progress) -> Outcome:
    label = f"#{pull.number}"
    view = json.loads(gh.read(repo, "pr", "view", str(pull.number), "--json", "state,baseRefName,headRefOid", sleep=sleep))
    reason = _refusal(view, pull, base)
    if reason:
        return Outcome(pull.number, pull.url, False, reason)
    if dry_run:
        failed, waiting = _check_state(_reported(repo, pull.number), required)
        verdict = f"required checks failed: {', '.join(failed)}" if failed else f"checks still to pass: {', '.join(waiting)}" if waiting else "ready to merge"
        return Outcome(pull.number, pull.url, False, f"dry run: {verdict}")
    progress(f"{label}: waiting for the required checks")
    reason = wait_for_checks(repo, pull.number, required, sleep)
    if reason:
        return Outcome(pull.number, pull.url, False, reason)
    progress(f"{label}: merging")
    gh.change(repo, "pr", "merge", str(pull.number), "--merge", "--delete-branch", "--match-head-commit", pull.head_sha)
    return Outcome(pull.number, pull.url, True)


def merge(
    repo: Path,
    summary: Summary,
    chosen: Sequence[Reviewed],
    confirm: Confirm,
    dry_run: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    progress: Progress = silent,
) -> list[Outcome]:
    """Merge `chosen` in number order once `confirm` agrees to the list. A pull request that cannot be merged is reported and the rest go on.

    `dry_run` reads each from GitHub as it stands and merges nothing, waits for nothing and asks nothing.
    """
    if not chosen:
        raise MergeError("no pull request to merge: none is at level `none`; name the ones you have read")
    try:
        gh.read(repo, "auth", "status", "--hostname", "github.com", sleep=sleep)
        required = required_checks(repo, summary.base, sleep)
    except (gh.GhError, LandError) as error:
        raise MergeError(str(error)) from error
    if not dry_run and not confirm(chosen):
        raise MergeError("not confirmed; nothing was merged")
    outcomes: list[Outcome] = []
    for pull in chosen:
        try:
            outcomes.append(_merge_one(repo, pull, summary.base, required, dry_run, sleep, progress))
        except (gh.GhError, ChecksUnreadable, CommandError, json.JSONDecodeError, KeyError) as error:
            outcomes.append(Outcome(pull.number, pull.url, False, f"GitHub said: {' '.join(str(error).split())}"))
    return outcomes
