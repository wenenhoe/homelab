#!/usr/bin/env python3
"""Do Molecule playbooks take their helper images from molecule_helpers/vars/images/?

Every image a converge, verify or cleanup playbook runs directly lives once,
in ansible/roles/molecule_helpers/vars/images/<name>.yml, as
`molecule_helpers_<name>_image: "<repo>:<tag>"`. Two things depend on that:

- Renovate's ansible manager only reads tasks/, so an image literal in a
  playbook is a pin nothing ever bumps; the regex manager in
  .github/renovate.json5 reads these files instead.
- CI queues a role by the files its scenarios reference (ci.scope.molecule_scope),
  so one file per image, loaded only by the plays that use it, is what makes
  an image bump rerun only the roles that use that image.

`check` fails on:

- an image file that isn't exactly one `molecule_helpers_<name>_image:
  "<repo>:<tag>"` line, with `<name>` the file's own name;
- a literal `<repo>:<tag>` of one of those images in a scenario's YAML outside
  its files/ directory (fixture compose files can't use variables and keep
  their own pin);
- a play that uses a variable whose file it doesn't load, or loads a file
  nothing it runs uses (a task file counts for the play that imports it);
- a task file using a variable that no play runs, or an image file no play
  loads.

Usage (from tools/): python -m ci.images.molecule_vars check
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ROLES_DIR = "ansible/roles"
VARS_DIR = f"{ROLES_DIR}/molecule_helpers/vars/images"

_DEFINITION = re.compile(r'^molecule_helpers_([a-z0-9_]+)_image:\s*"([^"\s:]+):([^"\s]+)"\s*$')
_USE = re.compile(r"molecule_helpers_([a-z0-9_]+)_image\b")
_LOAD = re.compile(r"""^\s*-\s*["']?\{\{\s*playbook_dir\s*\}\}/(\S*?/vars/images/([a-z0-9_]+)\.ya?ml)["']?\s*$""")
_IMPORT = re.compile(r"""(?:import_tasks|include_tasks):\s*["']?([\w./-]+\.ya?ml)["']?\s*$""")
_PLAY = re.compile(r"^(?:- +|  )hosts:", re.MULTILINE)
_TRAILING_COMMENT = re.compile(r"\s#.*$")


def _pins(root: Path) -> tuple[dict[str, tuple[str, str]], list[str]]:
    """{name: (repo, tag)} from vars/images/*.yml, and what's wrong with those files."""
    directory = root / VARS_DIR
    if not directory.is_dir():
        return {}, [f"{VARS_DIR} doesn't exist"]
    pins: dict[str, tuple[str, str]] = {}
    errors: list[str] = []
    for path in sorted(directory.glob("*.yml")):
        rel = path.relative_to(root)
        lines = [line for line in path.read_text().splitlines() if line.strip() and not line.lstrip().startswith("#") and line.strip() != "---"]
        match = _DEFINITION.match(lines[0]) if len(lines) == 1 else None
        if match is None:
            errors.append(
                f'{rel}: must hold exactly one `molecule_helpers_{path.stem}_image: "<repo>:<tag>"` line, quoted (Renovate\'s regex manager reads that shape)'
            )
        elif match.group(1) != path.stem:
            errors.append(f"{rel}: defines molecule_helpers_{match.group(1)}_image, but the file is named {path.stem}")
        else:
            pins[path.stem] = (match.group(2), match.group(3))
    return pins, errors


def _scenario_files(root: Path) -> Iterator[Path]:
    """Every YAML file in a role's molecule/ tree except fixtures under files/ and symlinks."""
    roles = root / ROLES_DIR
    if not roles.is_dir():
        return
    for role in sorted(roles.iterdir()):
        for directory, subdirs, names in os.walk(role / "molecule"):
            subdirs[:] = sorted(d for d in subdirs if d != "files" and not (Path(directory) / d).is_symlink())
            for name in sorted(names):
                path = Path(directory) / name
                if path.suffix in (".yml", ".yaml") and not path.is_symlink():
                    yield path


def _code_lines(text: str) -> list[tuple[int, str]]:
    """(line number, line) with whole-line and trailing YAML comments removed."""
    return [(n, _TRAILING_COMMENT.sub("", line)) for n, line in enumerate(text.splitlines(), 1) if not line.lstrip().startswith("#")]


def _imports(path: Path, texts: dict[Path, str]) -> list[Path]:
    targets = (path.parent / m.group(1) for _, line in _code_lines(texts[path]) if (m := _IMPORT.search(line)))
    return [target for target in targets if target in texts]


def _reach(path: Path, texts: dict[Path, str]) -> set[Path]:
    """The file and every task file it imports, transitively."""
    seen: set[Path] = set()
    stack = [path]
    while stack:
        current = stack.pop()
        if current not in seen:
            seen.add(current)
            stack.extend(_imports(current, texts))
    return seen


def _used(paths: set[Path], texts: dict[Path, str]) -> set[str]:
    return {m.group(1) for path in paths for _, line in _code_lines(texts[path]) for m in _USE.finditer(line)}


def _literals(root: Path, pins: dict[str, tuple[str, str]], texts: dict[Path, str]) -> list[str]:
    patterns = {name: re.compile(rf"(?<![\w./-]){re.escape(repo)}:[\w][\w.-]*") for name, (repo, _) in pins.items()}
    errors = []
    for path, text in texts.items():
        for number, line in _code_lines(text):
            for name, pattern in patterns.items():
                if found := pattern.search(line):
                    errors.append(
                        f"{path.relative_to(root)}:{number}: names {found.group(0)} literally; "
                        f"use {{{{ molecule_helpers_{name}_image }}}} and load vars/images/{name}.yml"
                    )
    return errors


def _play_errors(root: Path, play: Path, pins: dict[str, tuple[str, str]], texts: dict[Path, str]) -> tuple[list[str], set[str]]:
    """What's wrong with one play's loads against its own uses, and the image files it loads."""
    rel = play.relative_to(root)
    loaded: set[str] = set()
    errors = []
    for _, line in _code_lines(texts[play]):
        if match := _LOAD.match(line):
            name = match.group(2)
            if (play.parent / match.group(1)).resolve() != (root / VARS_DIR / f"{name}.yml").resolve():
                errors.append(f"{rel}: vars_files entry for {name} doesn't resolve to {VARS_DIR}/{name}.yml")
            else:
                loaded.add(name)
    used = _used(_reach(play, texts), texts)
    for name in sorted(used - loaded):
        errors.append(
            f"{rel}: uses molecule_helpers_{name}_image but doesn't load vars/images/{name}.yml"
            if name in pins
            else f"{rel}: uses molecule_helpers_{name}_image, which no file in {VARS_DIR} defines"
        )
    for name in sorted(loaded - used):
        errors.append(
            f"{rel}: loads vars/images/{name}.yml but nothing it runs uses molecule_helpers_{name}_image "
            "(an unused load reruns this role whenever that image is bumped)"
        )
    return errors, loaded


def check(root: Path) -> list[str]:
    """Every way a Molecule playbook has drifted from the shared image files."""
    root = root.resolve()
    pins, errors = _pins(root)
    texts = {path.resolve(): path.read_text() for path in _scenario_files(root)}
    errors += _literals(root, pins, texts)
    plays = [path for path, text in texts.items() if _PLAY.search(text)]
    reached: set[Path] = set()
    loaded: set[str] = set()
    for play in plays:
        play_errors, play_loaded = _play_errors(root, play, pins, texts)
        errors += play_errors
        loaded |= play_loaded
        reached |= _reach(play, texts)
    errors += [
        f"{path.relative_to(root)}: uses molecule_helpers_*_image but no play in this scenario runs it"
        for path in sorted(texts)
        if path not in reached and _used({path}, texts)
    ]
    errors += [f"{VARS_DIR}/{name}.yml: no play loads it" for name in sorted(set(pins) - loaded)]
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_subparsers(dest="command", required=True).add_parser("check")
    parser.parse_args(argv)
    errors = check(REPO_ROOT)
    for error in errors:
        print(f"::error::{error}")
    if not errors:
        print("Every Molecule playbook takes its helper images from molecule_helpers/vars/images/.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
