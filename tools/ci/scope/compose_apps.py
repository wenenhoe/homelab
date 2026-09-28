#!/usr/bin/env python3
"""Which docker/<app> stacks a run should boot-test, build, or syntax-check.

One reader for `.github/compose-boot-test-exclusions.txt` and one rule for
what makes a directory under docker/ a compose app, where pr-checks.yml's
detect-changes, its compose-syntax-check job and boot-test-all.yml's
list-apps each used to parse the exclusion list themselves.

An app is queued for a boot test when its `compose.yaml`/`compose.yaml.j2`
changes, its `Dockerfile` does (the boot test builds it in place of the
published image — see docs/ci.md#dockerfile-changes), or anything under its
`configs/` or `scripts/` does (the `compose` role renders and stages both
before the stack boots). Excluded apps are never queued, and a directory
with no compose file isn't an app.

Subcommands (from tools/: python -m ci.scope.compose_apps ...):
  changed <base> <head>       writes apps=<json> and dockerfiles=<json>
  all                         writes apps=<json>: every non-excluded compose app
  syntax-check <base> <head>  `docker compose config --quiet` on the changed
                              compose files of the excluded apps
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from ci.output import write_output
from ci.scope.diff import DiffError, changed_files

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCKER_DIR = "docker"
EXCLUSIONS_FILE = ".github/compose-boot-test-exclusions.txt"
COMPOSE_FILES = ("compose.yaml", "compose.yaml.j2")

_BOOT_TEST_INPUT = re.compile(r"^docker/([^/]+)/(?:compose\.yaml(?:\.j2)?|Dockerfile|(?:configs|scripts)/.+)$")
_DOCKERFILE = re.compile(r"^docker/([^/]+)/Dockerfile$")

# (args, cwd) -> exit code
Runner = Callable[[list[str], Path], int]


class ComposeAppsError(Exception):
    """Something needed to decide the app list is missing."""


def load_exclusions(root: Path) -> set[str]:
    """App names in the exclusions file: one per line, `#` comments and blanks ignored."""
    path = root / EXCLUSIONS_FILE
    try:
        text = path.read_text()
    except OSError as exc:
        raise ComposeAppsError(f"can't read {EXCLUSIONS_FILE}: {exc}") from exc
    lines = (line.strip() for line in text.splitlines())
    return {line for line in lines if line and not line.startswith("#")}


def has_compose(root: Path, app: str) -> bool:
    return any((root / DOCKER_DIR / app / name).is_file() for name in COMPOSE_FILES)


def all_apps(root: Path) -> list[str]:
    """Every non-excluded directory under docker/ that has a compose file, sorted."""
    excluded = load_exclusions(root)
    return sorted(d.name for d in (root / DOCKER_DIR).iterdir() if d.is_dir() and d.name not in excluded and has_compose(root, d.name))


def changed_apps(root: Path, changed: list[str]) -> list[str]:
    """Non-excluded compose apps whose boot-test inputs changed, sorted."""
    excluded = load_exclusions(root)
    candidates = {m.group(1) for path in changed if (m := _BOOT_TEST_INPUT.match(path))}
    return sorted(app for app in candidates if app not in excluded and has_compose(root, app))


def changed_dockerfiles(root: Path, changed: list[str]) -> list[str]:
    """Apps whose Dockerfile changed and still exists, excluded apps included."""
    candidates = {m.group(1) for path in changed if (m := _DOCKERFILE.match(path))}
    return sorted(app for app in candidates if (root / DOCKER_DIR / app / "Dockerfile").is_file())


def excluded_compose_files(root: Path, changed: list[str]) -> list[str]:
    """Changed `compose*.yaml` files, still present, under an excluded app.

    `.j2` templates aren't listed: they aren't valid compose until rendered.
    """
    excluded = load_exclusions(root)
    found = []
    for path in changed:
        parts = path.split("/")
        if len(parts) >= 3 and parts[0] == DOCKER_DIR and parts[1] in excluded and fnmatch.fnmatch(parts[-1], "compose*.yaml") and (root / path).is_file():
            found.append(path)
    return sorted(found)


def check_syntax(root: Path, files: list[str], run: Runner) -> list[str]:
    """Run `docker compose config --quiet` on each file; return the ones that failed.

    An explicit `env_file:` entry has to exist for `config --quiet` to pass,
    unlike the implicit top-level .env, and only syntax is being validated
    here, so an empty stub stands in for a missing one and is removed after.
    """
    failed = []
    for path in files:
        print(f"=== {path} ===")
        stub = (root / path).parent / ".env"
        created = not stub.exists()
        if created:
            stub.touch()
        try:
            code = run(["docker", "compose", "-f", path, "config", "--quiet"], root)
        finally:
            if created:
                stub.unlink(missing_ok=True)
        if code != 0:
            failed.append(path)
    return failed


def _run(args: list[str], cwd: Path) -> int:
    return subprocess.run(args, cwd=cwd, check=False).returncode


def _dump(items: list[str]) -> str:
    return json.dumps(items, separators=(",", ":"))


def main(argv: list[str] | None = None, run: Runner = _run) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("changed", "syntax-check"):
        command = sub.add_parser(name)
        command.add_argument("base")
        command.add_argument("head")
    sub.add_parser("all")
    args = parser.parse_args(argv)
    try:
        if args.command == "all":
            apps = all_apps(REPO_ROOT)
            print(f"Testing apps: {apps}")
            write_output("apps", _dump(apps))
        elif args.command == "changed":
            changed = changed_files(REPO_ROOT, args.base, args.head)
            apps, dockerfiles = changed_apps(REPO_ROOT, changed), changed_dockerfiles(REPO_ROOT, changed)
            print(f"Boot-testing: {apps}\nBuilding Dockerfiles: {dockerfiles}")
            write_output("apps", _dump(apps))
            write_output("dockerfiles", _dump(dockerfiles))
        else:
            files = excluded_compose_files(REPO_ROOT, changed_files(REPO_ROOT, args.base, args.head))
            if not files:
                print("No excluded-app compose files changed.")
                return 0
            failed = check_syntax(REPO_ROOT, files, run)
            for path in failed:
                print(f"::error::{path} isn't valid compose (docker compose config --quiet failed)")
            return 1 if failed else 0
    except (ComposeAppsError, DiffError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
