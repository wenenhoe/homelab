#!/usr/bin/env python3
"""Command blocks in the docs are safe to paste and keep secrets out of the command text.

The rules are AGENTS.md's "Command blocks for the operator". This checks the
part of them a script can decide, in every tracked or new markdown file
outside docs/decisions/:

- every code fence names a language;
- in a shell fence, no `<placeholder>`, `{{ variable }}` or `...` stands
  where a value goes;
- one fence holds at most one `# [n/m]` segment;
- a command that waits for input is the last command of its fence;
- no secret-named variable is assigned a literal value;
- `curl` is not given `-u` or `--user`, which shows in the process list.

Comments are not read, apart from the segment markers. Whether a value is
secret, and where a file lands, are left to review.

Usage:
    cd tools && python3 -m doc_scripts.check_command_blocks
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# A decision revision records what was true when it was written.
EXCLUDE_PREFIXES = ("docs/decisions/",)
SHELL_LANGS = frozenset({"sh", "bash", "shell"})

_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})\s*(.*)$")
_SEGMENT_RE = re.compile(r"^\s*#\s*\[\d+/\d+\]")
_PLACEHOLDER_RE = re.compile(r"(?<!<)<[A-Za-z][A-Za-z0-9_ .,'|/-]*>")
_TEMPLATE_RE = re.compile(r"\{\{\s*[a-z_]+\s*\}\}")
_ELLIPSIS_RE = re.compile(r"(?<=[=\s])\.\.\.(?=\s|$)")
_LITERAL_SECRET_RE = re.compile(r"\b[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSPHRASE|AUTHKEY|API_KEY)[A-Z0-9_]*=(?![$%\s]|[\"']\$|[\"']{2}|$)")
_CURL_USER_RE = re.compile(r"\bcurl\b[^|;&]*\s(?:-[A-Za-z]*u\b|--user\b)")
_PROMPT_RES = (
    # `read` fed by a pipe or a redirection takes no terminal input.
    re.compile(r"(?:^|;|&&|\|\|)\s*(?:IFS=\S*\s+)?read\s(?![^;&]*<)"),
    re.compile(r"\bopenbao_utils\.(?:shell|unseal)\b"),
    re.compile(r"(?:^|;|&&)\s*ssh(?:\s+-t)?\s+\"?(?:[\w.-]+@)?(?:[\w.-]+|\$\{?\w+\}?)\"?\s*$"),
    re.compile(r"\bsudo\s+-i\b"),
    re.compile(r"\bgpg\s[^;&|]*--(?:full-)?gen(?:erate)?-key\b"),
    re.compile(r"\bdocker\s+(?:run|exec)\b[^;&|]*\s-(?:it|ti)\b"),
)
_CLOSERS = frozenset({"done", "fi", "esac", "}"})


@dataclass(frozen=True)
class Fence:
    line: int  # of the opening marker
    lang: str
    body: tuple[str, ...]


def fences(text: str) -> Iterator[Fence]:
    """Every fenced code block, those indented under a list item included."""
    opening: tuple[str, int, str] | None = None
    body: list[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        match = _FENCE_RE.match(line)
        if opening is None:
            if match:
                opening, body = (match[1], number, match[2].strip()), []
        elif match and match[1].startswith(opening[0]) and not match[2]:
            yield Fence(opening[1], opening[2].split(" ")[0], tuple(body))
            opening = None
        else:
            body.append(line)


def strip_comment(line: str) -> str:
    """The line without its shell comment: a `#` outside quotes, at the start or after a space."""
    quote = ""
    for i, char in enumerate(line):
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "#" and (i == 0 or line[i - 1].isspace()):
            return line[:i]
    return line


def commands(body: tuple[str, ...]) -> list[tuple[int, str]]:
    """(offset of its first line in the body, text) of each command, continuations joined."""
    result: list[tuple[int, str]] = []
    pending, start = "", 0
    for offset, line in enumerate(body):
        code = strip_comment(line).rstrip()
        if not pending:
            start = offset
        if code.endswith("\\"):
            pending += code[:-1] + " "
            continue
        joined, pending = (pending + code).strip(), ""
        if joined:
            result.append((start, joined))
    return result


def block_errors(fence: Fence) -> list[tuple[int, str]]:
    """(line number, message) for each rule the fence breaks."""
    if not fence.lang:
        return [(fence.line, "code fence names no language (`sh` for commands, `text` for anything else)")]
    if fence.lang not in SHELL_LANGS:
        return []
    errors: list[tuple[int, str]] = []
    segments = [offset for offset, line in enumerate(fence.body) if _SEGMENT_RE.match(line)]
    if len(segments) > 1:
        errors.append((fence.line + 1 + segments[1], "second segment in one fence: give each segment its own fence"))
    found = commands(fence.body)
    for index, (offset, command) in enumerate(found):
        line = fence.line + 1 + offset
        if match := _PLACEHOLDER_RE.search(command) or _TEMPLATE_RE.search(command) or _ELLIPSIS_RE.search(command):
            errors.append((line, f"placeholder `{match[0]}`: set a variable, or `read` it in an earlier fence"))
        if match := _LITERAL_SECRET_RE.search(command):
            errors.append((line, f"literal value for `{match[0]}`: `read -rs` the secret or take it from its source"))
        if _CURL_USER_RE.search(command):
            errors.append((line, "`curl -u` shows the password in the process list: pass it to `curl -K -` on stdin"))
        if any(p.search(command) for p in _PROMPT_RES) and any(later not in _CLOSERS for _, later in found[index + 1 :]):
            errors.append((line, "a command that waits for input must end its fence, or the next lines are read as the input"))
    return errors


def markdown_files(root: Path = ROOT) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "--", "*.md"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [rel for rel in sorted(set(out.splitlines())) if not rel.startswith(EXCLUDE_PREFIXES) and (root / rel).is_file()]


def command_block_errors(root: Path = ROOT) -> list[str]:
    errors = []
    for rel in markdown_files(root):
        for fence in fences((root / rel).read_text(encoding="utf-8")):
            errors += [f"{rel}:{line}: {message}" for line, message in block_errors(fence)]
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=ROOT, help="repository root (tests point this at a temp repo)")
    args = ap.parse_args(argv)
    errors = command_block_errors(args.root)
    for e in errors:
        print(f"::error::{e}")
    if errors:
        print(f"\n{len(errors)} command block problem(s). The rules are in AGENTS.md.", file=sys.stderr)
        return 1
    print("Every command block passes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
