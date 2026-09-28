#!/usr/bin/env python3
"""Decides which roles pr-checks.yml's molecule job must test for a diff.

A role is queued when a changed file sits inside that role's *watch
set*: everything its Molecule run reads. The set is derived from the
checked-out tree on every run, so it cannot drift from what the
scenarios actually reference:

- the role's own directory;
- every role it runs: `include_role`/`import_role` names, play `roles:`
  entries and `meta` dependencies found in the scenario's playbooks, in
  the role's own tasks/handlers/meta, and in each included role's, so
  a change to a shared role queues every role whose Molecule run
  exercises it (the whole included role's directory is watched);
- every `molecule_helpers` task file a scenario pulls in through
  `include_role: {name: molecule_helpers, tasks_from: ...}`, followed
  transitively through the helper playbooks/task files that themselves
  include further helper task files or roles;
- every `${MOLECULE_PROJECT_DIRECTORY}/...` path in a scenario's
  molecule.yml (the shared `prepare` playbooks);
- the resolved target of every symlink under `molecule/` (scenarios
  link the real `docker/<app>/` files and `molecule_helpers/fixtures/`
  into their own `files/`; git reports the target path, never the link);
- files read by a path built from `playbook_dir` (the scenario
  directory under Molecule): `playbook_dir ~ '/../x'`,
  `{{ playbook_dir }}/../x`, and the same through any variable a
  scenario defines as `{{ playbook_dir }}` or
  `{{ (playbook_dir ~ '...') | realpath }}` (`project_root`,
  `repo_root`, ...), in the scenario's files and in the role's own.

Two fail-safes always err toward testing more, never less: a changed
file under `molecule_helpers/` that no scenario references queues every
role, and so does a path in GLOBAL_PATHS. A reference the scanner can't
resolve (a templated `include_role` name, a role that doesn't exist, a
dangling symlink, a missing `tasks_from` file) raises ScopeError and
fails the job instead of being skipped.

Before matching, a changed file whose parsed content is identical in
base and head (comments or formatting only; see semantic_diff.py) is
dropped from the diff, so it queues nothing, not even through the
fail-safes.

Not modelled: paths built any other way (a variable not defined as
above, a literal continued with `~`), and reads through a file's
runtime contents. Computed paths that don't exist, that resolve outside
the repo, or that are the role's own directory or an ancestor of it are
ignored.

Usage (from tools/): python -m ci_scope.molecule_scope <base-sha> <head-sha>
Writes roles=<json array> to $GITHUB_OUTPUT (stdout if unset).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import yaml

from ci_scope import semantic_diff

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


_INCLUDE_KEYS = ("include_role", "import_role")


def _role_entry_name(yaml_path: Path, entry) -> str:
    """The role name in a `roles:`/`dependencies:` entry (a string or a mapping)."""
    name = entry if isinstance(entry, str) else (entry.get("role") or entry.get("name")) if isinstance(entry, dict) else None
    if not isinstance(name, str):
        raise ScopeError(f"{yaml_path}: unsupported role entry {entry!r} (expected a name or a mapping with role/name)")
    return name


def _yaml_refs(root: Path, yaml_path: Path) -> tuple[set[str], set[str]]:
    """(molecule_helpers task files, other local role names) that `yaml_path` runs."""
    helper_tasks: set[str] = set()
    role_refs: set[str] = set()

    def add_role(name: str, tasks_from: object = "main") -> None:
        if "{{" in name or "{{" in str(tasks_from):
            raise ScopeError(f"{yaml_path}: templated role name/tasks_from can't be scanned: {name} / {tasks_from}")
        if name == HELPERS_ROLE:
            helper_tasks.add(_resolve_helper_task(root, yaml_path, str(tasks_from)))
        elif "." in name:
            return  # a collection role (namespace.collection.role), not part of this repo
        elif "/" in name or not (root / ROLES_DIR / name).is_dir():
            raise ScopeError(f"{yaml_path}: role {name!r} is not a directory under {ROLES_DIR}/")
        else:
            role_refs.add(name)

    for doc in _load_yaml(yaml_path):
        for node in _walk(doc):
            if not isinstance(node, dict):
                continue
            for key, value in node.items():
                if isinstance(key, str) and key.rsplit(".", 1)[-1] in _INCLUDE_KEYS:
                    if not isinstance(value, dict) or not isinstance(value.get("name"), str):
                        raise ScopeError(f"{yaml_path}: unsupported {key} shape (expected a mapping with a literal name)")
                    add_role(value["name"], value.get("tasks_from", "main"))
            if "hosts" in node and isinstance(node.get("roles"), list):
                for entry in node["roles"]:
                    add_role(_role_entry_name(yaml_path, entry))
        if yaml_path.parent.name == "meta" and isinstance(doc, dict):
            for entry in doc.get("dependencies") or []:
                add_role(_role_entry_name(yaml_path, entry))
    return helper_tasks, role_refs


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


def _role_production_yaml(role_dir: Path):
    """The YAML Ansible runs when a role is included (not its Molecule scenarios)."""
    for sub in ("tasks", "handlers", "meta"):
        base = role_dir / sub
        if base.is_dir():
            yield from sorted(p for p in base.rglob("*") if p.is_file() and p.suffix in YAML_SUFFIXES)


def _role_text_files(role_dir: Path):
    """Every YAML/Jinja file in a role outside molecule/, where a path may be built."""
    for path in sorted(role_dir.rglob("*")):
        if path.is_file() and path.suffix in (*YAML_SUFFIXES, ".j2") and "molecule" not in path.relative_to(role_dir).parts[:1]:
            yield path


_PATH_VAR_PLAIN = re.compile(r"^\{\{\s*playbook_dir\s*\}\}$")
_PATH_VAR_REALPATH = re.compile(r"^\{\{\s*\(?\s*playbook_dir\s*~\s*'([^'{}]*)'\s*\)?\s*\|\s*realpath\s*\}\}$")


def _path_vars(scenario_dir: Path, scenario_yaml: list[Path]) -> dict[str, set[Path]]:
    """Variables a scenario defines as a directory derived from playbook_dir."""
    found: dict[str, set[Path]] = {"playbook_dir": {scenario_dir}}
    for yml in scenario_yaml:
        for doc in _load_yaml(yml):
            for node in _walk(doc):
                if not isinstance(node, dict):
                    continue
                for key, value in node.items():
                    if not isinstance(key, str) or not isinstance(value, str):
                        continue
                    if _PATH_VAR_PLAIN.match(value):
                        found.setdefault(key, set()).add(scenario_dir)
                    elif match := _PATH_VAR_REALPATH.match(value):
                        found.setdefault(key, set()).add(Path(os.path.normpath(f"{scenario_dir}{match.group(1)}")))
    return found


def _computed_paths(root: Path, role_dir: Path, scenario_dir: Path, scenario_yaml: list[Path], texts: list[Path]) -> dict[str, str]:
    """Existing repo paths built from a scenario's path variables -> where they were built."""
    resolved_root = root.resolve()
    role_resolved = role_dir.resolve()
    found: dict[str, str] = {}
    path_vars = _path_vars(scenario_dir, scenario_yaml)
    for text_path in texts:
        text = text_path.read_text()
        for var, anchors in path_vars.items():
            literals = re.findall(rf"(?<![\w.]){re.escape(var)}\s*~\s*'(/[^'{{}}\n]*)'(?!\s*~)", text)
            literals += re.findall(rf"\{{\{{\s*{re.escape(var)}\s*\}}\}}(/[^\s\"'{{}}]*)", text)
            for literal in literals:
                for anchor in anchors:
                    candidate = Path(os.path.normpath(f"{anchor}{literal}"))
                    try:
                        rel = candidate.relative_to(resolved_root).as_posix()
                    except ValueError:
                        continue
                    if not candidate.exists() or candidate == resolved_root or candidate in (role_resolved, *role_resolved.parents):
                        continue
                    if candidate.is_relative_to(role_resolved):
                        continue
                    found.setdefault(rel + "/" if candidate.is_dir() else rel, _relative(resolved_root, text_path.resolve()))
    return found


def watch_set(root: Path, role: str) -> dict[str, list[str]]:
    """Watched path -> why it's watched. Paths ending `/` are directory prefixes."""
    role_dir = root / ROLES_DIR / role
    molecule_dir = role_dir / "molecule"
    watched: dict[str, list[str]] = {f"{ROLES_DIR}/{role}/": ["role directory"]}
    scannable = (f"{HELPERS_DIR}/playbooks/", f"{HELPERS_DIR}/tasks/")

    def watch(path: str, reason: str) -> None:
        watched.setdefault(path, []).append(reason)

    # (file to scan for includes, label used in the reason text)
    pending: list[tuple[Path, str]] = []
    visited_roles = {role}
    for yml in _role_production_yaml(role_dir):
        pending.append((yml, _relative(root, yml)))

    scenario_yaml: dict[Path, list[Path]] = {}
    for yml in _scenario_yaml_files(molecule_dir):
        label = _relative(root, yml)
        pending.append((yml, label))
        scenario_yaml.setdefault(yml.parent if yml.parent.parent == molecule_dir else molecule_dir / yml.relative_to(molecule_dir).parts[0], []).append(yml)
        if yml.name == "molecule.yml":
            for path in sorted(_token_paths(root, role_dir, yml)):
                watch(path, f"referenced by {label}")
                if path.startswith(scannable) and path.endswith(YAML_SUFFIXES):
                    pending.append((root / path, path))
    for path in sorted(_symlink_targets(root, molecule_dir)):
        watch(path, "symlink target under molecule/")

    # Paths built from playbook_dir, in the scenario's files and the role's own.
    role_texts = list(_role_text_files(role_dir))
    for scenario_dir, ymls in sorted(scenario_yaml.items()):
        for path, source in sorted(_computed_paths(root, role_dir, scenario_dir, ymls, [*ymls, *role_texts]).items()):
            watch(path, f"computed path in {source}")

    # A helper playbook, helper task file or included role can itself
    # include further helper task files or roles, so follow the
    # references to a fixed point.
    seen: set[Path] = set()
    while pending:
        yml, label = pending.pop()
        if yml in seen:
            continue
        seen.add(yml)
        helper_tasks, role_refs = _yaml_refs(root, yml)
        for ref in sorted(helper_tasks):
            watch(ref, f"tasks_from in {label}")
            pending.append((root / ref, ref))
        for included in sorted(role_refs - visited_roles):
            visited_roles.add(included)
            watch(f"{ROLES_DIR}/{included}/", f"runs role {included} ({label})")
            pending.extend((prod, _relative(root, prod)) for prod in _role_production_yaml(root / ROLES_DIR / included))
    return watched


def _matches(changed: str, watched_path: str) -> bool:
    return changed.startswith(watched_path) if watched_path.endswith("/") else changed == watched_path


def roles_to_test(root: Path, changed: list[str], is_noop: Callable[[str], bool] | None = None) -> tuple[list[str], list[str]]:
    """(roles, log lines) for a list of changed repo-relative paths.

    `is_noop` says a path's change is comments or formatting only; such
    paths are dropped before anything is matched.
    """
    roles = role_names(root)
    log: list[str] = []
    effective: list[str] = []
    for path in changed:
        if is_noop is not None and is_noop(path):
            log.append(f"{path}: comments/formatting only -> ignored")
        else:
            effective.append(path)

    for path in effective:
        for global_path in GLOBAL_PATHS:
            if _matches(path, global_path):
                log.append(f"{path}: repo-wide ({global_path}) -> every role")
                return roles, log

    watches = {role: watch_set(root, role) for role in roles}
    queued: set[str] = set()
    for path in effective:
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
        roles, log = roles_to_test(
            REPO_ROOT,
            changed_files(REPO_ROOT, args.base, args.head),
            lambda path: semantic_diff.is_noop_between(REPO_ROOT, args.base, args.head, path),
        )
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
