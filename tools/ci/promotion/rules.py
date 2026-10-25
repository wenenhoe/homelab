"""Which paths ask for which command.

The CD agent deploys `main` by itself, so the checklist lists only what it does
not apply: the operator host's own toolchain, the CD agent's own provisioning
and the Tofu-managed machines. A rule fires when any changed path matches one of
its `patterns` and none of its `exclude`; the rules keep this order, which is the
order to run them in.

Patterns are globs over repository paths: `*` stays inside one directory, `**`
crosses directories, and `**/` also matches no directory at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache


@dataclass(frozen=True)
class Rule:
    command: str
    patterns: tuple[str, ...]
    where: str
    exclude: tuple[str, ...] = ()


RULES: tuple[Rule, ...] = (
    Rule(
        command="uv sync",
        patterns=("pyproject.toml", "uv.lock"),
        where="the repository root on the operator host",
    ),
    Rule(
        command="ansible-galaxy collection install -r requirements.yml",
        patterns=("ansible/requirements.yml",),
        where="`ansible/` on the operator host",
    ),
    Rule(
        command="ansible-playbook playbooks/cd-agent.yaml",
        patterns=(
            "ansible/roles/cd_agent/**",
            "ansible/playbooks/cd-agent.yaml",
            "ansible/inventory/group_vars/cd_agent.yaml",
            "tools/cd_agent/**",
        ),
        where="`ansible/` on the operator host; the CD agent never provisions itself",
    ),
    Rule(
        command="tofu -chdir=tofu plan",
        patterns=("tofu/**",),
        exclude=("tofu/**/tests/**",),
        where="the repository root on the operator host; read the plan, then `tofu -chdir=tofu apply` with the same variables",
    ),
)


@cache
def _regex(pattern: str) -> re.Pattern[str]:
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out))


def matches(path: str, pattern: str) -> bool:
    return _regex(pattern).fullmatch(path) is not None


@dataclass(frozen=True)
class Item:
    rule: Rule
    paths: tuple[str, ...]


def checklist(changed: list[str], rules: tuple[Rule, ...] = RULES) -> list[Item]:
    """The rules a set of changed paths fires, each with the paths that fired it."""
    items = []
    for rule in rules:
        hit = sorted({p for p in changed if any(matches(p, g) for g in rule.patterns) and not any(matches(p, g) for g in rule.exclude)})
        if hit:
            items.append(Item(rule, tuple(hit)))
    return items
