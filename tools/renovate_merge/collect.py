"""The open Renovate pull requests into a branch, each with its updates, release notes and flags."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from renovate_merge import changelog, flags, gh

FIELDS = "number,title,url,body,headRefName,headRefOid,baseRefName,isCrossRepository,author"
BRANCH_PREFIX = "renovate/"
LIST_LIMIT = "200"


@dataclass(frozen=True)
class Pull:
    number: int
    title: str
    url: str
    head_sha: str
    updates: list[changelog.Update]
    notes: str
    flags: list[flags.Flag]
    level: str


def is_renovate(item: dict) -> bool:
    """A branch of this repository named like Renovate's, opened by a login that names Renovate: either alone is something anyone can write."""
    login = (item.get("author") or {}).get("login") or ""
    return not item["isCrossRepository"] and item["headRefName"].startswith(BRANCH_PREFIX) and "renovate" in login.lower()


def build(item: dict) -> Pull:
    body = item.get("body") or ""
    text = changelog.notes(body)
    changes = changelog.updates(body)
    # Renovate's own warnings sit outside the release notes; every other pattern is read from the notes alone, since the table is links and badges.
    found = flags.scan(text) + [flag for flag in flags.scan(body.replace(text, "")) if flag.category == "warning"]
    return Pull(item["number"], item["title"], item["url"], item["headRefOid"], changes, text, found, flags.level(changes, found))


def collect(repo: Path, base: str, sleep: Callable[[float], None] = time.sleep) -> list[Pull]:
    """Renovate's open pull requests into `base`, by number."""
    listed = json.loads(gh.read(repo, "pr", "list", "--base", base, "--state", "open", "--limit", LIST_LIMIT, "--json", FIELDS, sleep=sleep) or "[]")
    return sorted((build(item) for item in listed if is_renovate(item)), key=lambda pull: pull.number)
