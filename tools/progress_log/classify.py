"""Sorting one change into a category and a group, by rule from its paths and title.

Nothing here reads git or writes files, and nothing calls a model: the same
change always lands in the same place.
"""

from __future__ import annotations

import re
from collections import Counter

# Generated from the docs themselves, so a change that only regenerates them says nothing about the work.
VIEWS = ("docs/decisions/README.md", "docs/projects/README.md", "docs/project-planning.md")
PROJECT_DOC = re.compile(r"^docs/projects/([^/]+)\.md$")
NOT_PROJECTS = ("README", "TEMPLATE")
CONVENTIONAL = re.compile(r"^(\w+)(?:\([^)]*\))?!?:\s*")
BOT_TITLE = re.compile(r"^(chore|fix)\((deps|ci)\)|lock file maintenance", re.IGNORECASE)

TYPE_ALIASES = {"hotfix": "fix", "cleanup": "chore", "misc": "chore", "dep": "chore", "style": "chore", "wip": "chore", "docsa": "docs", "build": "ci"}
KNOWN_TYPES = {"feat", "fix", "docs", "refactor", "ci", "test", "chore", "revert", "perf"}
REPO_CONFIG_FILES = (".pre-commit-config.yaml", "pyproject.toml", "uv.lock")

DEPENDENCY_UPDATES = "Dependency updates"
DECISIONS = "Decisions"
SEVERAL_PROJECTS = "Project planning (several projects)"
PROJECT_PREFIX = "Project: "


def humanise(slug: str) -> str:
    return slug.replace("-", " ")


def normalise_type(commit_type: str) -> str:
    commit_type = TYPE_ALIASES.get(commit_type, commit_type)
    return commit_type if commit_type in KNOWN_TYPES else "other"


def bucket(path: str) -> str:
    """The area of the repo a path belongs to, named by its path."""
    if path.startswith("docs/"):
        return "docs/"
    if path.startswith("ansible/roles/"):
        return "ansible/roles/"
    if path.startswith("ansible/"):
        return "ansible/ (playbooks, inventory)"
    if path.startswith("docker/"):
        return "docker/"
    if path.startswith("tools/"):
        return "tools/"
    if path.startswith((".github/", ".config/", ".githooks/")) or path in REPO_CONFIG_FILES:
        return ".github/ and repo config"
    return path.split("/", 1)[0] + "/" if "/" in path else "Root files"


def project_slugs(paths: list[str]) -> list[str]:
    return sorted({m.group(1) for path in paths if (m := PROJECT_DOC.match(path)) and m.group(1) not in NOT_PROJECTS})


def category(paths: list[str], bot: bool) -> str:
    """`dep` (a bot's update), `built` (touches anything outside docs/), `scope` (only project docs) or `planned` (other docs and decisions)."""
    real = [path for path in paths if path not in VIEWS]
    if bot:
        return "dep"
    if any(not path.startswith("docs/") for path in real):
        return "built"
    if real and all(path.startswith("docs/projects/") for path in real):
        return "scope"
    return "planned"


def group(paths: list[str], bot: bool, title: str, events: list[list[str]]) -> str:
    """The theme a change is listed under: a project, then decisions, then the area most of its code is in.

    A change often touches several project docs (re-scoping, consolidating), so
    the project is chosen by evidence, not alphabetically: a state change in
    this change, or the slug's words appearing in its title.
    """
    if bot:
        return DEPENDENCY_UPDATES
    touched = project_slugs(paths)
    real = [path for path in paths if path not in VIEWS]
    if touched:
        changed = {event[1] for event in events if event[0] == "project"}
        words = set(re.findall(r"[a-z0-9]+", title.lower()))

        def score(slug: str) -> int:
            tokens = set(slug.split("-"))
            return (3 if slug in changed else 0) + (2 if len(tokens & words) / len(tokens) >= 0.5 else 0)

        best = max(touched, key=lambda slug: (score(slug), slug))
        if score(best) >= 2 or len(touched) == 1:
            return f"{PROJECT_PREFIX}{best}"
        if all(path.startswith("docs/") for path in real):
            return SEVERAL_PROJECTS
    if real and all(path.startswith("docs/decisions/") for path in real):
        return DECISIONS
    code = [path for path in real if not path.startswith("docs/")]
    areas = Counter(bucket(path) for path in (code or real))
    return areas.most_common(1)[0][0] if areas else "Root files"
