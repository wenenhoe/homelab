#!/usr/bin/env python3
"""The Bats clones the shell tests run on, pinned by commit, and a check that each pin is what its release tag names.

`pins.txt` lists each repository with a release tag and the full commit SHA the
tag points at. `check` resolves every tag with `git ls-remote` and fails when
it does not point at the pinned SHA: a SHA copied wrongly, or a tag that was
moved. That is the listed tier of ADR 0077, since no current key is published
to verify the signed tags against.

A repository, a tag and a SHA go to `git` as arguments and come from a file a
pull request changes, so each is accepted only in the shape a GitHub
repository, a release tag and a commit have.

A failure of any entry fails the run, a repository that cannot be reached
included: a pin that could not be checked has not been shown to be the
publisher's. A call that exits non-zero is made up to three times; a tag that
is missing or moved is a clean answer and is not retried. Needs `git`.
Standard library only.

Usage (from tools/): python3 -m ci.shell_tests.pins check [PINFILE]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ci import proc
from ci.output import write_summary
from ci.verification import ATTEMPTS, backoff

PIN_FILE = Path(__file__).with_name("pins.txt")
GITHUB = "https://github.com/"
_REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*")
_TAG = re.compile(r"v?[0-9][0-9A-Za-z.+_-]*")
_SHA = re.compile(r"[0-9a-f]{40}")
_READ_ERRORS = (OSError, UnicodeDecodeError)


class PinError(Exception):
    """The pin file can't be read, or a line of it isn't a pin."""


@dataclass(frozen=True)
class Pin:
    repository: str  # owner/name on GitHub
    tag: str
    sha: str

    @property
    def name(self) -> str:
        """The repository's own name, which is the directory a fetch clones it into."""
        return self.repository.split("/")[1]

    def url(self, base: str = GITHUB) -> str:
        return f"{base}{self.repository}.git"


def parse(text: str) -> list[Pin]:
    """Every pin in `text`: blank lines and `#` comments are skipped, and each other line is `repository tag sha`."""
    pins: list[Pin] = []
    problems: list[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 3:
            problems.append(f"line {number}: expected `repository tag sha`, got {len(fields)} field(s)")
            continue
        repository, tag, sha = fields
        if not _REPOSITORY.fullmatch(repository):
            problems.append(f"line {number}: {repository!r} isn't an owner/name GitHub repository")
        elif not _TAG.fullmatch(tag):
            problems.append(f"line {number}: {tag!r} isn't shaped like a release tag")
        elif not _SHA.fullmatch(sha):
            problems.append(f"line {number}: {sha!r} isn't a full lower-case commit SHA")
        else:
            pins.append(Pin(repository, tag, sha))
    names = [pin.name for pin in pins]
    problems += [f"two entries are named {name}, so one clone would replace the other" for name in sorted(set(names)) if names.count(name) > 1]
    if not pins and not problems:
        problems.append("lists no pins")
    if problems:
        raise PinError("; ".join(problems))
    return pins


def load(path: Path = PIN_FILE) -> list[Pin]:
    try:
        text = path.read_text()
    except _READ_ERRORS as exc:
        raise PinError(f"can't read {path.name}: {exc}") from exc
    try:
        return parse(text)
    except PinError as exc:
        raise PinError(f"{path.name}: {exc}") from exc


def resolve(pin: Pin, base: str, run: proc.Runner, sleep: Callable[[float], None] = time.sleep, attempts: int = ATTEMPTS) -> str | None:
    """The commit `pin.tag` points at in the remote, or None when it has no such tag.

    An annotated tag is a tag object and ls-remote lists the commit under the
    peeled `^{}` name; a lightweight tag is the commit, listed under its own
    name.
    """
    ref = f"refs/tags/{pin.tag}"
    argv = ["git", "ls-remote", pin.url(base), ref, f"{ref}^{{}}"]
    code = 0
    for attempt in range(attempts):
        if attempt:
            sleep(backoff(attempt))
        done = run(argv, Path.cwd(), True)
        if done.returncode == 0:
            listed = dict(line.split("\t", 1)[::-1] for line in done.stdout.splitlines() if "\t" in line)
            return listed.get(f"{ref}^{{}}") or listed.get(ref)
        code = done.returncode
    raise PinError(f"git ls-remote exited {code} after {attempts} attempts")


def check(pins: list[Pin], base: str = GITHUB, run: proc.Runner = proc.run, sleep: Callable[[float], None] = time.sleep) -> list[str]:
    """One message per pin whose tag does not point at its SHA."""
    errors = []
    for pin in pins:
        try:
            found = resolve(pin, base, run, sleep)
        except FileNotFoundError:
            return ["git is not installed"]
        except PinError as exc:
            errors.append(f"{pin.repository} {pin.tag}: {exc}")
            continue
        if found is None:
            errors.append(f"{pin.repository} has no tag {pin.tag}")
        elif found != pin.sha:
            errors.append(f"{pin.repository} {pin.tag} points at {found}, not the pinned {pin.sha}")
    return errors


def report(pins: list[Pin], errors: list[str]) -> tuple[list[str], int]:
    """(lines to print, exit code)."""
    lines = [f"::error::{error}" for error in errors]
    lines.append(f"{len(pins)} pins: {'all tags point at their SHAs' if not errors else f'{len(errors)} failed'}")
    return lines, 1 if errors else 0


def main(argv: list[str] | None = None, base: str = GITHUB, run: proc.Runner = proc.run, sleep: Callable[[float], None] = time.sleep) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    checking = commands.add_parser("check", help="require each pinned tag to point at its pinned SHA")
    checking.add_argument("pinfile", nargs="?", type=Path, default=PIN_FILE)
    args = parser.parse_args(argv)
    # A repository that doesn't exist makes git ask for a username, and nothing is there to answer.
    os.environ.setdefault("GIT_TERMINAL_PROMPT", "0")
    try:
        pins = load(args.pinfile)
    except PinError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    lines, code = report(pins, check(pins, base, run, sleep))
    print("\n".join(lines))
    write_summary("Shell test pins", lines)
    return code


if __name__ == "__main__":
    sys.exit(main())
