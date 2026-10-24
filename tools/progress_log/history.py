"""Reading `main`'s first-parent history into one record per merged change.

A PR merge is one record; so is a direct commit from before the PR workflow.
"""

from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from progress_log import classify

TZ = timezone(timedelta(hours=8))  # Asia/Singapore, which has no daylight saving; weeks run Monday to Sunday
RECORD, FIELD = "\x1e", "\x1f"
ADR_DOC = re.compile(r"^docs/decisions/(\d{4})-([^/]+)/revision-(\d+(?:-[a-z])?)\.md$")
# What counts as a component of the homelab; one file's appearing or going is the component's.
COMPONENTS = (
    (re.compile(r"^docker/([^/]+)/compose\.ya?ml(?:\.j2)?$"), "app"),
    (re.compile(r"^ansible/roles/([^/]+)/tasks/main\.ya?ml$"), "role"),
)
MERGE = re.compile(r"Merge pull request #(\d+) from [^/]+/(.+)")


class GitError(RuntimeError):
    pass


def git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, errors="replace", check=False)
    if check and result.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


def is_ancestor(repo: Path, commit: str, descendant: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", commit, descendant], capture_output=True, check=False).returncode == 0


def frontmatter_status(repo: Path, rev: str, path: str) -> str | None:
    """The `status:` of a markdown file's frontmatter at a revision, or None if it has none."""
    text = git(repo, "show", f"{rev}:{path}", check=False)
    block = re.match(r"---\n(.*?)\n---", text, re.DOTALL)
    status = re.search(r"^status:\s*(\S+)", block.group(1), re.MULTILINE) if block else None
    return status.group(1).strip("'\"") if status else None


def _status_change(repo: Path, before: str | None, after: str, path: str) -> str | None:
    if not before:
        return None
    was, now = frontmatter_status(repo, before, path), frontmatter_status(repo, after, path)
    return f"{was} → {now}" if was and now and was != now else None


def _events(repo: Path, sha: str, before: str | None, files: list[tuple[str, str]]) -> list[list[str]]:
    events: list[list[str]] = []
    components: dict[tuple[str, str], set[str]] = defaultdict(set)
    for status, path in files:
        if project := classify.project_slugs([path]):
            slug = project[0]
            if status == "A":
                events.append(["project", slug, f"opened ({frontmatter_status(repo, sha, path)})"])
            elif status == "D":
                events.append(["project", slug, "closed"])
            elif status == "M" and (change := _status_change(repo, before, sha, path)):
                events.append(["project", slug, change])
        elif m := ADR_DOC.match(path):
            label = f"ADR {m.group(1)} r{m.group(3)} · {classify.humanise(m.group(2))}"
            if status == "A":
                events.append(["adr", label, f"added ({frontmatter_status(repo, sha, path)})"])
            elif status == "M" and (change := _status_change(repo, before, sha, path)):
                events.append(["adr", label, change])
        for pattern, kind in COMPONENTS:
            if (m := pattern.match(path)) and status in "AD":
                components[(kind, m.group(1))].add(status)
    for (kind, name), statuses in components.items():
        if len(statuses) == 1:  # added and deleted in one change is a rename, not an add or a removal
            events.append(["component", f"{kind} {name}", "added" if "A" in statuses else "removed"])
    return events


def _title(subject: str, body: str, pr: int | None, branch: str | None) -> str:
    title = (body.strip().splitlines() or [""])[0] if pr else subject
    if pr and not title:  # a merge with no body: the branch name is all there is
        title = classify.humanise(re.sub(r"^\w+-", "", branch or ""))
    return title


def parse_units(repo: Path, rev_range: list[str]) -> list[dict]:
    """One record per first-parent change in `rev_range`, oldest first."""
    log = git(
        repo, "log", "--first-parent", "-m", "--no-renames", "--reverse", "--name-status",
        f"--format={RECORD}%H{FIELD}%P{FIELD}%cI{FIELD}%s{FIELD}%b{FIELD}", *rev_range,
    )  # fmt: skip
    units = []
    for record in log.split(RECORD)[1:]:
        sha, parents, committed, subject, body, rest = record.split(FIELD, 5)
        before = parents.split()[0] if parents.split() else None
        files = [(line[0], line.split("\t", 1)[1]) for line in rest.splitlines() if "\t" in line]
        merge = MERGE.match(subject)
        pr, branch = (int(merge.group(1)), merge.group(2)) if merge else (None, None)
        title = _title(subject, body, pr, branch)
        conventional = classify.CONVENTIONAL.match(title)
        commit_type = conventional.group(1).lower() if conventional else (branch.split("-")[0] if branch else "other")
        title = classify.CONVENTIONAL.sub("", title, count=1) or title
        bot = (branch or "").startswith("renovate/") or bool(classify.BOT_TITLE.search(f"{subject} {title}"))
        paths = [path for _, path in files]
        events = _events(repo, sha, before, files)
        units.append({
            "cat": classify.category(paths, bot),
            "sha": sha,
            "date": datetime.fromisoformat(committed).astimezone(TZ).isoformat(),
            "kind": "pr" if pr else "direct",
            "pr": pr,
            "title": title.strip(),
            "type": classify.normalise_type(commit_type),
            "bot": bot,
            "group": classify.group(paths, bot, title, events),
            "events": events,
        })  # fmt: skip
    return units
