#!/usr/bin/env python3
"""Decides which roles pr-checks.yml's molecule job must test for a diff.

A role is queued when a changed file sits inside that role's *watch
set*: everything its Molecule run reads. The set is derived from the
checked-out tree on every run, so it cannot drift from what the
scenarios actually reference:

- the role's own directory;
- every `molecule_helpers` task file a scenario pulls in through
  `include_role: {name: molecule_helpers, tasks_from: ...}`, followed
  transitively through the helper playbooks/task files that themselves
  include other helper task files;
- every `${MOLECULE_PROJECT_DIRECTORY}/...` path in a scenario's
  molecule.yml (the shared `prepare` playbooks);
- the resolved target of every symlink under `molecule/` (scenarios
  link the real `docker/<app>/` files and `molecule_helpers/fixtures/`
  into their own `files/`; git reports the target path, never the link).

Two fail-safes always err toward testing more, never less: a changed
file under `molecule_helpers/` that no scenario references queues every
role, and so does a path in GLOBAL_PATHS. A reference the scanner can't
resolve (a templated `include_role` name, a dangling symlink, a missing
`tasks_from` file) raises ScopeError and fails the job instead of being
skipped.

Not modelled: files a role reads by computed path (for example
`lookup('file', project_root ~ ...)`), and role-to-role `include_role`
edges (a change to an included role queues only that role).

Usage: molecule_scope.py <base-sha> <head-sha>
Writes roles=<json array> to $GITHUB_OUTPUT (stdout if unset).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ROLES_DIR = "ansible/roles"
HELPERS_ROLE = "molecule_helpers"
HELPERS_DIR = f"{ROLES_DIR}/{HELPERS_ROLE}"
PROJECT_DIR_TOKEN = "${MOLECULE_PROJECT_DIRECTORY}"  # noqa: S105 - Molecule's env var name, not a credential
YAML_SUFFIXES = (".yml", ".yaml")

# Paths every scenario inherits regardless of what it references: the
# base config's Galaxy inputs (.config/molecule/config.yml deep-merges
# it into every scenario) and the toolchain pins. tools/tests/ci_scope
# asserts the base config still points at the files listed here.
GLOBAL_PATHS = (
    ".config/molecule/",
    "ansible/requirements.yml",
    f"{HELPERS_DIR}/requirements.yml",
    f"{HELPERS_DIR}/role-requirements.yml",
    "pyproject.toml",
    "uv.lock",
)


class ScopeError(Exception):
    """A reference the scanner can't resolve safely."""


def role_names(root: Path) -> list[str]:
    """Every role that has a molecule/ directory, sorted."""
    roles_dir = root / ROLES_DIR
    return sorted(d.name for d in roles_dir.iterdir() if (d / "molecule").is_dir())


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        raise ScopeError(f"{path} resolves outside the repository") from None


def _load_yaml(path: Path) -> list:
    try:
        return [d for d in yaml.safe_load_all(path.read_text()) if d is not None]
    except yaml.YAMLError as exc:
        raise ScopeError(f"{path}: not parseable as YAML: {exc}") from exc


def _walk(node):
    """Every mapping and list element in a parsed YAML document."""
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _helper_task_refs(root: Path, yaml_path: Path) -> set[str]:
    """Repo-relative molecule_helpers task files that `yaml_path` includes."""
    refs: set[str] = set()
    for doc in _load_yaml(yaml_path):
        for node in _walk(doc):
            if not isinstance(node, dict):
                continue
            for key, value in node.items():
                if not isinstance(key, str) or key.rsplit(".", 1)[-1] not in ("include_role", "import_role"):
                    continue
                if not isinstance(value, dict) or not isinstance(value.get("name"), str):
                    raise ScopeError(f"{yaml_path}: unsupported {key} shape (expected a mapping with a literal name)")
                name = value["name"]
                tasks_from = value.get("tasks_from", "main")
                if "{{" in name or "{{" in str(tasks_from):
                    raise ScopeError(f"{yaml_path}: templated {key} name/tasks_from can't be scanned: {value}")
                if name == HELPERS_ROLE:
                    refs.add(_resolve_helper_task(root, yaml_path, str(tasks_from)))
    return refs


def _resolve_helper_task(root: Path, referrer: Path, tasks_from: str) -> str:
    tasks_dir = root / HELPERS_DIR / "tasks"
    candidates = [tasks_from] if tasks_from.endswith(YAML_SUFFIXES) else [f"{tasks_from}{s}" for s in YAML_SUFFIXES]
    for candidate in candidates:
        if (tasks_dir / candidate).is_file():
            return f"{HELPERS_DIR}/tasks/{candidate}"
    raise ScopeError(f"{referrer}: tasks_from {tasks_from!r} matches no file under {HELPERS_DIR}/tasks/")


def _scenario_yaml_files(molecule_dir: Path):
    """Playbooks and vars inside each scenario, skipping its fixture `files/` tree."""
    for dirpath, dirnames, filenames in os.walk(molecule_dir):
        if Path(dirpath).parent == molecule_dir:
            # Inside a scenario directory: `files/` holds fixtures and symlinks, not playbooks.
            dirnames[:] = [d for d in dirnames if d != "files"]
        for filename in sorted(filenames):
            if filename.endswith(YAML_SUFFIXES):
                yield Path(dirpath) / filename


def _token_paths(root: Path, role_dir: Path, molecule_yml: Path) -> set[str]:
    """Paths written as `${MOLECULE_PROJECT_DIRECTORY}/...` in a molecule.yml."""
    found: set[str] = set()
    for doc in _load_yaml(molecule_yml):
        for node in _walk(doc):
            if not isinstance(node, str) or PROJECT_DIR_TOKEN not in node:
                continue
            if not node.startswith(PROJECT_DIR_TOKEN):
                raise ScopeError(f"{molecule_yml}: {PROJECT_DIR_TOKEN} used mid-string, can't resolve: {node}")
            resolved = Path(os.path.normpath(str(role_dir) + node[len(PROJECT_DIR_TOKEN) :]))
            rel = _relative(root, resolved)
            if not resolved.exists():
                raise ScopeError(f"{molecule_yml}: {node} resolves to {rel}, which doesn't exist")
            found.add(rel + "/" if resolved.is_dir() else rel)
    return found


def _symlink_targets(root: Path, molecule_dir: Path) -> set[str]:
    found: set[str] = set()
    resolved_root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(molecule_dir, followlinks=False):
        for name in dirnames + filenames:
            link = Path(dirpath) / name
            if not link.is_symlink():
                continue
            target = Path(os.path.realpath(link))
            if not target.exists():
                raise ScopeError(f"{link}: dangling symlink")
            rel = _relative(resolved_root, target)
            found.add(rel + "/" if target.is_dir() else rel)
    return found


def watch_set(root: Path, role: str) -> dict[str, list[str]]:
    """Watched path -> why it's watched. Paths ending `/` are directory prefixes."""
    role_dir = root / ROLES_DIR / role
    molecule_dir = role_dir / "molecule"
    watched: dict[str, list[str]] = {f"{ROLES_DIR}/{role}/": ["role directory"]}
    scannable = (f"{HELPERS_DIR}/playbooks/", f"{HELPERS_DIR}/tasks/")

    # (file to scan for helper includes, label used in the reason text)
    pending: list[tuple[Path, str]] = []
    for yml in _scenario_yaml_files(molecule_dir):
        label = _relative(root, yml)
        pending.append((yml, label))
        if yml.name == "molecule.yml":
            for path in sorted(_token_paths(root, role_dir, yml)):
                watched.setdefault(path, []).append(f"referenced by {label}")
                if path.startswith(scannable) and path.endswith(YAML_SUFFIXES):
                    pending.append((root / path, path))
    for path in sorted(_symlink_targets(root, molecule_dir)):
        watched.setdefault(path, []).append("symlink target under molecule/")

    # A helper playbook or task file can itself include further helper
    # task files, so follow the references to a fixed point.
    seen: set[Path] = set()
    while pending:
        yml, label = pending.pop()
        if yml in seen:
            continue
        seen.add(yml)
        for ref in sorted(_helper_task_refs(root, yml)):
            watched.setdefault(ref, []).append(f"tasks_from in {label}")
            pending.append((root / ref, ref))
    return watched


def _matches(changed: str, watched_path: str) -> bool:
    return changed.startswith(watched_path) if watched_path.endswith("/") else changed == watched_path


def roles_to_test(root: Path, changed: list[str]) -> tuple[list[str], list[str]]:
    """(roles, log lines) for a list of changed repo-relative paths."""
    roles = role_names(root)
    log: list[str] = []
    for path in changed:
        for global_path in GLOBAL_PATHS:
            if _matches(path, global_path):
                log.append(f"{path}: repo-wide ({global_path}) -> every role")
                return roles, log

    watches = {role: watch_set(root, role) for role in roles}
    queued: set[str] = set()
    for path in changed:
        hit = False
        for role, watched in watches.items():
            for watched_path, reasons in watched.items():
                if _matches(path, watched_path):
                    queued.add(role)
                    hit = True
                    log.append(f"{path}: {role} ({reasons[0]})")
                    break
        if not hit and path.startswith(f"{HELPERS_DIR}/"):
            log.append(f"{path}: under {HELPERS_ROLE}/ but no scenario references it -> every role")
            return roles, log
    return sorted(queued), log


def changed_files(root: Path, base: str, head: str) -> list[str]:
    # --no-renames lists both sides of a rename, so a file moved out of a
    # watched path still counts as touching it.
    result = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", base, head],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ScopeError(f"git diff failed: {result.stderr.strip()}")
    return [line for line in result.stdout.splitlines() if line]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("base")
    parser.add_argument("head")
    args = parser.parse_args(argv)
    try:
        roles, log = roles_to_test(REPO_ROOT, changed_files(REPO_ROOT, args.base, args.head))
    except ScopeError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    print("\n".join(log))
    line = f"roles={json.dumps(roles, separators=(',', ':'))}"
    print(f"Testing roles: {roles}")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a") as fh:
            fh.write(line + "\n")
    else:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
