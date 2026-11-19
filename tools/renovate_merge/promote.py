"""Open the pull request that promotes `maintenance` into `main`, with a description of what the batch holds, and stop there.

The merge is the maintainer's: it deploys, so it is made by hand with a merge commit and the bypass (`docs/topics/engineering/branching.md`).
Nothing here changes `main`, and nothing here merges.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from land_series.run import CommandError, checked

from renovate_merge import gh
from renovate_merge.collect import FIELDS, LIST_LIMIT, build, is_renovate
from renovate_merge.report import cell

REMOTE = "origin"
TARGET = "main"
SOURCE = "maintenance"
GIT_TIMEOUT_SECONDS = 300.0
PULL_MERGE_RE = re.compile(r"^Merge pull request #(\d+) from (\S+)")
MAX_OTHER_COMMITS = 10
BRANCHING_DOC = "docs/topics/engineering/branching.md"

Confirm = Callable[["Batch"], bool]


class PromoteError(Exception):
    """The pull request was not opened."""


@dataclass(frozen=True)
class Entry:
    """A pull request merged into the source branch. `level` and `matches` are set for Renovate's, which are the ones that were read."""

    number: int
    title: str
    level: str | None = None
    matches: tuple[str, ...] = ()


@dataclass(frozen=True)
class Batch:
    entries: list[Entry]
    other_commits: list[str]  # subjects of commits on the source branch that came by neither a pull request nor a merge of `main`

    @property
    def title(self) -> str:
        count = len(self.entries)
        return f"chore(deps): promote {count} update{'' if count == 1 else 's'} from {SOURCE}" if count else f"chore(deps): promote {SOURCE}"


def _git(repo: Path, *args: str) -> str:
    try:
        return checked(["git", "-C", str(repo), *args], timeout=GIT_TIMEOUT_SECONDS).text
    except CommandError as error:
        raise PromoteError(" ".join(str(error).split())) from error


def fetch(repo: Path) -> None:
    """Bring both branches up to date, so the batch is what GitHub holds and not what this clone last saw."""
    _git(repo, "fetch", "--quiet", REMOTE, TARGET, SOURCE)


def history(repo: Path) -> tuple[list[tuple[int, str]], list[str]]:
    """What the source branch has that the target lacks, along its own line: the pull requests merged into it, and any other commit on it.

    A merge of `main` into it, which Renovate's workflow makes before each run, is neither.
    """
    log = _git(repo, "log", "--first-parent", "--format=%P%x09%s", f"{REMOTE}/{TARGET}..{REMOTE}/{SOURCE}")
    pulls: list[tuple[int, str]] = []
    other: list[str] = []
    for line in log.splitlines():
        parents, _, subject = line.partition("\t")
        merged = PULL_MERGE_RE.match(subject)
        if merged:
            pulls.append((int(merged.group(1)), merged.group(2)))
        elif len(parents.split()) == 1:
            other.append(subject)
    return sorted(pulls), other


def batch(repo: Path, sleep: Callable[[float], None] = time.sleep) -> Batch:
    pulls, other = history(repo)
    if not pulls and not other:
        raise PromoteError(f"{SOURCE} holds nothing that {TARGET} lacks")
    merged = ["pr", "list", "--base", SOURCE, "--state", "merged", "--limit", LIST_LIMIT, "--json", FIELDS]
    listed = json.loads(gh.read(repo, *merged, sleep=sleep) or "[]")
    known = {item["number"]: item for item in listed}
    entries: list[Entry] = []
    for number, branch in pulls:
        item = known.get(number)
        if item is None:
            entries.append(Entry(number, branch))
        elif is_renovate(item):
            read = build(item)
            entries.append(Entry(number, read.title, read.level, tuple(sorted({flag.category for flag in read.flags}))))
        else:
            entries.append(Entry(number, item["title"]))
    return Batch(entries, other)


def code(text: str) -> str:
    """`text` as an inline code span, so an `@name` in a package's title notifies nobody and nothing in it is read as Markdown."""
    flat = " ".join(text.split())
    marks = "`" * (max((len(run) for run in re.findall(r"`+", flat)), default=0) + 1)
    return f"{marks} {flat} {marks}"


def body(found: Batch) -> str:
    lines = [
        f"Promotes {SOURCE} into {TARGET}: {len(found.entries)} pull request{'' if len(found.entries) == 1 else 's'} "
        f"merged into {SOURCE} since {TARGET} last held it."
    ]
    if found.entries:
        lines += ["", "| PR | Title | Level | Matches |", "| :--- | :--- | :--- | :--- |"]
        lines += [f"| #{entry.number} | {cell(code(entry.title))} | {entry.level or '—'} | {', '.join(entry.matches) or '—'} |" for entry in found.entries]
        lines += [
            "",
            "A level is the one `renovate_merge summary` gives a Renovate pull request from its description: `breaking` is a major version, a stated "
            "breaking change or a warning, `notable` a weaker match, `none` no match. "
            "`—` is a pull request that is not Renovate's, or one GitHub no longer lists.",
        ]
    if found.other_commits:
        shown = found.other_commits[:MAX_OTHER_COMMITS]
        lines += ["", f"Also on {SOURCE}, not from a pull request:", ""]
        lines += [f"- {code(subject)}" for subject in shown]
        if len(found.other_commits) > len(shown):
            lines.append(f"- and {len(found.other_commits) - len(shown)} more")
    lines += ["", f"Merge it with a merge commit, using the bypass, and never squash: {BRANCHING_DOC} says why."]
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class Opened:
    url: str
    created: bool


def promote(repo: Path, confirm: Confirm, dry_run: bool = False, sleep: Callable[[float], None] = time.sleep) -> tuple[Batch, Opened | None]:
    """Open the promotion pull request unless one is open already, in which case it is left as it is: a workflow keeps a checklist in its description."""
    try:
        gh.read(repo, "auth", "status", "--hostname", "github.com", sleep=sleep)
    except gh.GhError as error:
        raise PromoteError(str(error)) from error
    fetch(repo)
    found = batch(repo, sleep)
    try:
        opened_now = ["pr", "list", "--head", SOURCE, "--base", TARGET, "--state", "open", "--json", "number,url,isCrossRepository"]
        open_now = json.loads(gh.read(repo, *opened_now, sleep=sleep) or "[]")
        existing = [item for item in open_now if not item["isCrossRepository"]]
        if existing:
            return found, Opened(existing[0]["url"], created=False)
        if dry_run:
            return found, None
        if not confirm(found):
            raise PromoteError("not confirmed; no pull request was opened")
        url = gh.change(repo, "pr", "create", "--base", TARGET, "--head", SOURCE, "--title", found.title, "--body", body(found)).splitlines()[-1]
    except gh.GhError as error:
        raise PromoteError(str(error)) from error
    return found, Opened(url, created=True)


def describe(found: Batch) -> list[str]:
    """The lines a confirmation shows: the title, then how many pull requests are at each level."""
    counts: dict[str, int] = {}
    for entry in found.entries:
        key = entry.level or "not Renovate's"
        counts[key] = counts.get(key, 0) + 1
    return [found.title, *(f"  {count}  {key}" for key, count in sorted(counts.items()))]
