#!/usr/bin/env python3
"""molecule-coverage: static task inventory

Enumerates every task defined anywhere under <role>/tasks/, recursing into
block/rescue/always, so it can later be diffed against the JSONL execution
records written by callback_plugins/molecule_coverage.py.

Deliberately does NOT follow include_tasks/import_tasks/include_role -
each task file is scanned independently:
  - include_tasks/import_tasks targets are scanned anyway because every
    *.yaml/*.yml under tasks/ is globbed directly, regardless of whether
    anything actually includes it.
  - include_role targets point at a *different* role's tasks/, which has
    its own, separate inventory - following it here would double-count
    those tasks against this role.

Also excludes import_tasks/import_role/meta statements themselves from
the inventory (see _STRUCTURALLY_UNMEASURABLE_ACTIONS) - Ansible never
fires a runtime event for these specific statements (verified
empirically), so including them would produce permanent, unfixable
"never_observed" false negatives regardless of actual test coverage.

This means dead/unreachable task files would currently be silently
included as "should be covered" - a known limitation, not a goal for this
stage.

Usage:
    python3 inventory.py ansible/roles/caddy
    python3 inventory.py ansible/roles/caddy --coverage-dir tools/molecule-coverage/.data
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from ansible.errors import AnsibleParserError
from ansible.parsing.dataloader import DataLoader
from ansible.parsing.mod_args import ModuleArgsParser

try:
    # ansible-core >= 2.19's data-tagging rewrite: position info is carried
    # as an Origin tag rather than the old `ansible_pos` attribute.
    from ansible._internal._datatag._tags import Origin
except ImportError:  # pragma: no cover - older ansible-core
    Origin = None

# Keys that, when present on a task dict, mark it as a block/rescue/always
# container rather than a leaf task. Ansible never fires a runner_on_*
# event for the container itself - only for the tasks nested inside it -
# so containers must be recursed into but not recorded as tasks.
_BLOCK_KEYS = ("block", "rescue", "always")

# Actions that can never show as "covered" no matter how well-tested they
# are, because Ansible never fires a runner_on_ok/skipped/failed event for
# the statement itself - verified empirically (not from docs), see the
# conversation this was diagnosed in:
#   - import_tasks/import_role are expanded at PARSE time, not run time:
#     their content is spliced directly into the surrounding task list
#     before execution, so the statement itself has no corresponding
#     runtime node. The tasks it pulls in are still correctly measured -
#     under the imported file's own name/line, not this one. (Contrast
#     with include_tasks/include_role, which ARE dynamic/runtime and DO
#     fire their own event in addition to the included tasks.)
#   - meta (e.g. flush_handlers) is handled directly by Ansible's
#     strategy plugin, never dispatched through the normal task executor
#     that the callback plugin's hooks are attached to.
# Including these in the inventory would make them permanent, unfixable
# false negatives ("never_observed" forever, regardless of test quality),
# so they're excluded from the denominator entirely rather than counted
# against coverage.
_STRUCTURALLY_UNMEASURABLE_ACTIONS = {
    "ansible.builtin.import_tasks",
    "import_tasks",
    "ansible.builtin.import_role",
    "import_role",
    "ansible.builtin.meta",
    "meta",
}

# Keys that mark a task as looped. Only `loop:` is actually used anywhere
# in this repo (verified via grep), but the legacy with_* family is
# included too since it's cheap and future-proofs against anyone adding
# one later - Ansible treats them identically at runtime for callback
# purposes (same item_on_ok/skipped/failed hooks fire either way).
_LOOP_KEYS = (
    "loop",
    "with_items",
    "with_list",
    "with_dict",
    "with_together",
    "with_nested",
    "with_sequence",
    "with_fileglob",
    "with_subelements",
    "with_flattened",
)


def _iter_task_files(role_dir: Path) -> list[Path]:
    tasks_dir = role_dir / "tasks"
    if not tasks_dir.is_dir():
        return []
    files = {p for p in tasks_dir.rglob("*.yaml")} | {p for p in tasks_dir.rglob("*.yml")}
    return sorted(files)


def _task_position(task_ds) -> tuple[str | None, int | None]:
    # Modern ansible-core (>=2.19) tags parsed mappings with an Origin tag
    # carrying path/line_num/col_num - the replacement for the older
    # ansible_pos attribute, and what Task.get_path() now derives from,
    # so this lines up with what the callback plugin records.
    if Origin is not None:
        origin = Origin.get_tag(task_ds)
        if origin is not None:
            return origin.path, origin.line_num
    # Fall back to the pre-2.19 attribute, in case this ever runs against
    # an older ansible-core.
    pos = getattr(task_ds, "ansible_pos", None)
    if pos:
        file_, line, _col = pos
        return file_, line
    return None, None


def _resolve_action(task_ds) -> str | None:
    try:
        # skip_action_validation=True: we only want to know *which* key is
        # the action (e.g. "ansible.builtin.file"), not whether that module
        # actually resolves/loads - resolution can fail for third-party
        # collection modules in environments where they aren't installed,
        # which would otherwise silently hide the action name.
        action, _args, _delegate_to = ModuleArgsParser(task_ds).parse(skip_action_validation=True)
        return action
    except AnsibleParserError:
        return None


def _walk(task_list, results: list[dict]) -> None:
    if not task_list:
        return
    for item in task_list:
        if not isinstance(item, dict):
            continue
        if any(key in item for key in _BLOCK_KEYS):
            for key in _BLOCK_KEYS:
                if item.get(key):
                    _walk(item[key], results)
            continue
        file_, line = _task_position(item)
        action = _resolve_action(item)
        if action in _STRUCTURALLY_UNMEASURABLE_ACTIONS:
            continue
        results.append(
            {
                "task_name": item.get("name"),
                "task_file": file_,
                "task_line": line,
                "action": action,
                "has_loop": any(key in item for key in _LOOP_KEYS),
            }
        )


def scan_role(role_dir: Path) -> list[dict]:
    loader = DataLoader()
    results: list[dict] = []
    for task_file in _iter_task_files(role_dir):
        data = loader.load_from_file(str(task_file))
        _walk(data, results)
    # Stable ordering: by file, then line.
    results.sort(key=lambda t: (t["task_file"] or "", t["task_line"] or 0))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role_dir", type=Path, help="Path to a role directory, e.g. ansible/roles/caddy")
    parser.add_argument(
        "--coverage-dir",
        type=Path,
        default=Path(os.environ.get("MOLECULE_COVERAGE_DIR", "./.molecule-coverage-data")),
        help="Directory to write <role>/_inventory.json into (same root the callback plugin writes JSONL under).",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print the inventory to stdout instead of writing a file.",
    )
    args = parser.parse_args()

    role_dir = args.role_dir.resolve()
    if not role_dir.is_dir():
        print(f"error: {role_dir} is not a directory", file=sys.stderr)
        return 1

    inventory = scan_role(role_dir)
    role_name = role_dir.name

    if args.stdout:
        print(json.dumps(inventory, indent=2))
        return 0

    out_path = args.coverage_dir / role_name / "_inventory.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(inventory)} task(s) to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
