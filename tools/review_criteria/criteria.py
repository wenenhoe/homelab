"""The criteria that say a change is worth asking for a review, decided from the diff alone.

Each criterion is a plain rule about paths and changed lines, so the same diff always gives the same
answer. A major criterion recommends a review on its own; the two minor ones recommend it only when both
trip. A criterion looks at substantive lines only: a blank line, a comment line, or any line of a
markdown file does not count, so a docs-only change never recommends one.

The criteria are advice for the person landing the change. Nothing here blocks anything.

Standard library only.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath

MAJOR, MINOR = "major", "minor"

# A change this size, or this many files, is worth a second look when it also ships code with no test.
# Placeholders to tune against what the maintainer finds noisy; generous on purpose.
MINOR_LINES = 800
MINOR_FILES = 30

AUTOMATION_PREFIXES = (".github/", ".githooks/", "tools/cd_agent/", "tools/land_series/", "tools/openbao_utils/", "tools/cloud_credentials/")
AUTOMATION_FILES = ("pyproject.toml", "uv.lock")
SECRET_ROLES = ("secrets", "openbao", "openbao_cli", "step_ca_cert", "step_ca_client", "tinyauth", "tinyauth_ca_trust")
SECRET_COMPOSE = ("openbao", "step-ca", "tinyauth")
SECRET_FILES = ("ansible/inventory/group_vars/all/secret_catalog.yaml",)
BACKUP_ROLES = ("backup_agent", "restore", "restore_discovery", "cloud_sync")
APP_CATALOG = "ansible/inventory/group_vars/all/app_catalog.yaml"
EXPOSURE_GATE = "tools/ci/gates/app_catalog_rules.py"
HARDENING_GATE = "tools/ci/gates/compose_hardening_rules.py"
CODE_SUFFIXES = (".py", ".sh", ".tf")
GENERATED_FILES = ("uv.lock",)

ROUTE_LINE = re.compile(r"^\s*upstream:")
BACKUP_LINE = re.compile(r"^\s*backup(_defaults)?:")
PORT_LINE = re.compile(r"""^\s*-\s*["']?(\d{1,3}(\.\d{1,3}){3}:)?\d+(-\d+)?:\d+(-\d+)?(/(tcp|udp))?["']?\s*(#.*)?$""")


@dataclass(frozen=True)
class Change:
    """One file of a diff: the lines it adds and the lines it removes."""

    path: str
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()

    @property
    def substantive(self) -> tuple[str, ...]:
        """The changed lines that count: not blank, not a comment, and none at all in a markdown file."""
        if self.path.endswith(".md"):
            return ()
        return tuple(line for line in (*self.added, *self.removed) if line.strip() and not line.lstrip().startswith(("#", "//")))


@dataclass(frozen=True)
class Criterion:
    id: str
    kind: str
    summary: str
    matches: Callable[[list[Change]], list[str]]


@dataclass(frozen=True)
class Hit:
    criterion: Criterion
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class Assessment:
    hits: tuple[Hit, ...]

    @property
    def recommend(self) -> bool:
        """True when a major criterion tripped or both minor ones did."""
        majors = [hit for hit in self.hits if hit.criterion.kind == MAJOR]
        minors = [hit for hit in self.hits if hit.criterion.kind == MINOR]
        return bool(majors) or len(minors) == len(MINOR_CRITERIA)


def _under(path: str, prefixes: Iterable[str]) -> bool:
    return any(path.startswith(prefix) for prefix in prefixes)


def _is_test(path: str) -> bool:
    name = PurePosixPath(path).name
    return "/tests/" in f"/{path}" or "/molecule/" in f"/{path}" or name.startswith("test_") or name.endswith(".bats")


def _is_compose(path: str) -> bool:
    return path.startswith("docker/") and PurePosixPath(path).name.startswith("compose")


def _is_doc(path: str) -> bool:
    return path.startswith("docs/") or path.endswith(".md")


def _paths(changes: list[Change], wanted: Callable[[str], bool]) -> list[str]:
    return sorted(change.path for change in changes if change.substantive and wanted(change.path))


def _lines(changes: list[Change], path: str, pattern: re.Pattern[str], *, removed: bool = False) -> list[str]:
    return sorted(
        {
            change.path
            for change in changes
            if change.path == path and any(pattern.match(line) for line in (*change.added, *(change.removed if removed else ())))
        }
    )


def _automation(changes: list[Change]) -> list[str]:
    return _paths(changes, lambda p: ((_under(p, AUTOMATION_PREFIXES) and not _is_test(p)) or p in AUTOMATION_FILES) and not p.endswith(".md"))


def _secrets(changes: list[Change]) -> list[str]:
    role_prefixes = tuple(f"ansible/roles/{role}/" for role in SECRET_ROLES)
    compose_prefixes = tuple(f"docker/{name}/" for name in SECRET_COMPOSE)
    return _paths(changes, lambda p: (_under(p, (*role_prefixes, *compose_prefixes)) and "/molecule/" not in p) or p in SECRET_FILES)


def _exposure(changes: list[Change]) -> list[str]:
    ports = sorted({c.path for c in changes if _is_compose(c.path) and any(PORT_LINE.match(line) for line in c.added)})
    return sorted({*_lines(changes, APP_CATALOG, ROUTE_LINE), *ports, *_paths(changes, lambda p: p == EXPOSURE_GATE)})


def _hardening(changes: list[Change]) -> list[str]:
    return _paths(changes, lambda p: p == HARDENING_GATE)


def _backup(changes: list[Change]) -> list[str]:
    role_prefixes = tuple(f"ansible/roles/{role}/" for role in BACKUP_ROLES)
    return sorted({*_paths(changes, lambda p: _under(p, role_prefixes) and "/molecule/" not in p), *_lines(changes, APP_CATALOG, BACKUP_LINE, removed=True)})


def _tofu(changes: list[Change]) -> list[str]:
    def production(path: str) -> bool:
        if not path.startswith("tofu/") or not path.endswith((".tf", ".tfvars")) or _is_test(path):
            return False
        return path.startswith("tofu/modules/") or "/" not in path.removeprefix("tofu/")

    return _paths(changes, production)


def _untested_code(changes: list[Change]) -> list[str]:
    code = _paths(changes, lambda p: p.endswith(CODE_SUFFIXES) and not _is_test(p))
    return code if code and not _paths(changes, _is_test) else []


def _large(changes: list[Change]) -> list[str]:
    counted = [c for c in changes if not _is_doc(c.path) and c.path not in GENERATED_FILES]
    lines = sum(len(c.substantive) for c in counted)
    files = sum(1 for c in counted if c.substantive)
    return [f"{lines} changed lines in {files} files"] if lines >= MINOR_LINES or files >= MINOR_FILES else []


MAJOR_CRITERIA = (
    Criterion(
        "R1", MAJOR, "automation or a tool that holds credentials or deploys: workflows, git hooks, dependencies, the deploy and credential tools", _automation
    ),
    Criterion("R2", MAJOR, "secrets handling: the secrets, OpenBao, step-ca and Tinyauth roles and services, and the secret catalog", _secrets),
    Criterion("R3", MAJOR, "what is reachable: a new route or published port, or a change to the check that governs open routes", _exposure),
    Criterion("R4", MAJOR, "a change to the check that holds container hardening, or to what it excuses", _hardening),
    Criterion("R5", MAJOR, "backup, restore or off-site sync, or a service's declared backup", _backup),
    Criterion("R6", MAJOR, "production OpenTofu: the root files and modules", _tofu),
)
MINOR_CRITERIA = (
    Criterion("r1", MINOR, "code changed with no test changed", _untested_code),
    Criterion("r2", MINOR, f"a large change: {MINOR_LINES} or more changed lines, or {MINOR_FILES} or more files", _large),
)
CRITERIA = (*MAJOR_CRITERIA, *MINOR_CRITERIA)


def assess(changes: list[Change]) -> Assessment:
    """Which criteria `changes` trip, in the order the criteria are listed."""
    hits = []
    for criterion in CRITERIA:
        evidence = criterion.matches(changes)
        if evidence:
            hits.append(Hit(criterion, tuple(evidence)))
    return Assessment(tuple(hits))


def parse_diff(text: str) -> list[Change]:
    """The files of a `git diff -U0 --no-renames` output with the lines each adds and removes."""
    files: dict[str, tuple[list[str], list[str]]] = {}
    current: tuple[list[str], list[str]] | None = None
    old_path = ""
    for line in text.splitlines():
        if line.startswith("--- "):
            old_path = line[4:].removeprefix("a/")
        elif line.startswith("+++ "):
            new_path = line[4:].removeprefix("b/")
            path = old_path if new_path == "/dev/null" else new_path
            current = files.setdefault(path, ([], []))
        elif current is not None and line.startswith("+"):
            current[0].append(line[1:])
        elif current is not None and line.startswith("-"):
            current[1].append(line[1:])
        elif line.startswith("diff --git "):
            current = None
    return [Change(path, tuple(added), tuple(removed)) for path, (added, removed) in files.items()]


def read_changes(repo: str, base: str, head: str) -> list[Change]:
    """The changes from `base` to `head` in the git repository at `repo`."""
    result = subprocess.run(
        ["git", "-C", repo, "diff", "-U0", "--no-renames", "--no-color", "--no-ext-diff", base, head, "--"],
        check=True,
        capture_output=True,
        text=True,
    )
    return parse_diff(result.stdout)


def describe(assessment: Assessment) -> list[str]:
    """One line for each criterion that tripped, with the files that tripped it."""
    return [f"{hit.criterion.id}: {hit.criterion.summary} ({', '.join(hit.evidence[:3])}{', ...' if len(hit.evidence) > 3 else ''})" for hit in assessment.hits]
