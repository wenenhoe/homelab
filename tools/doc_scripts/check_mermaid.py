#!/usr/bin/env python3
"""Fails when a Mermaid diagram in the repo's markdown does not render (ADR 0078).

Finds every fenced `mermaid` block in the tracked markdown files and renders each
one with the pinned mermaid-cli container image, the block's text on stdin. For
every block that does not render it prints the file, the line the block starts on
and the renderer's first error message. It reads markdown and changes nothing.

Needs Docker and nothing else: the image carries the CLI and its browser.

Usage (from tools/): python -m doc_scripts.check_mermaid [FILE ...]

Without FILE it checks every tracked .md file. Exit status: 0 when every block
renders or there are none, 1 when a block does not render, 2 when Docker could
not run the image, so no verdict was reached.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MERMAID_CLI_IMAGE = "ghcr.io/mermaid-js/mermaid-cli/mermaid-cli:12.0.0"
# Each container starts a browser, so this bounds memory as well as time.
WORKERS = 4
BLOCK_TIMEOUT = 120
PULL_TIMEOUT = 600
# The CLI reads the block from stdin and writes its SVG inside the container, which is discarded.
RUN_ARGS = [
    "docker",
    "run",
    "--rm",
    "-i",
    "--network",
    "none",
    "--cap-drop",
    "ALL",
    "--security-opt",
    "no-new-privileges",
    MERMAID_CLI_IMAGE,
    "-i",
    "-",
    "-o",
    "/tmp/diagram.svg",  # noqa: S108 - a path inside the container, not on the host
]
# `docker run` exits with these when docker itself failed, not the CLI in the container.
DOCKER_FAILED = (125, 126, 127)
MESSAGE_LINES = 6
# Named, not written inline: `ruff format` targets 3.14 and drops the parentheses from a bare
# `except (A, B):`, which older Pythons (the runner's python3) can't parse.
_RUN_ERRORS = (OSError, subprocess.TimeoutExpired)

_FENCE = re.compile(r"^(?P<indent> *)(?P<fence>`{3,}|~{3,})(?P<info>.*)$")
# The CLI prints the error's class and message, then a blank line and a Node stack made of
# "    at ..." frames and "name (url:line:col)" ones.
_ERROR_LINE = re.compile(r"^\w*Error: ")
_STACK_FRAME = re.compile(r"^\s+at |:\d+:\d+\)$")

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class DockerError(Exception):
    """Docker could not run the image, so no block can be given a verdict."""


@dataclass(frozen=True)
class Block:
    path: str
    line: int  # 1-based, of the opening fence
    text: str


def find_blocks(text: str, path: str) -> list[Block]:
    """Every fenced block whose info string starts with `mermaid`.

    A fence closes on a line of the same character at least as long as the one that
    opened it, so a mermaid fence quoted inside a longer fence is that fence's content,
    not a block. An unclosed fence runs to the end of the text, as markdown renders it.
    """
    lines = text.splitlines()
    blocks: list[Block] = []
    i = 0
    while i < len(lines):
        opening = _FENCE.match(lines[i])
        if not opening or (opening["fence"][0] == "`" and "`" in opening["info"]):
            i += 1
            continue
        fence, indent = opening["fence"], len(opening["indent"])
        closing = re.compile(rf" *{re.escape(fence[0])}{{{len(fence)},}}\s*$")
        end = i + 1
        while end < len(lines) and not closing.match(lines[end]):
            end += 1
        if opening["info"].split()[:1] == ["mermaid"]:
            body = [re.sub(rf"^ {{0,{indent}}}", "", line) for line in lines[i + 1 : end]]
            blocks.append(Block(path, i + 1, "\n".join(body)))
        i = end + 1
    return blocks


def error_message(returncode: int, stdout: str, stderr: str) -> str:
    """The CLI's own message for a block it could not render, without the stack behind it."""
    lines = stderr.splitlines()
    for start, line in enumerate(lines):
        if _ERROR_LINE.match(line):
            message: list[str] = []
            for candidate in lines[start:]:
                if not candidate.strip() or _STACK_FRAME.search(candidate):
                    break
                message.append(candidate.rstrip())
            return "\n".join(message[:MESSAGE_LINES]).removeprefix("Error: ")
    tail = [line.rstrip() for line in (stderr or stdout).splitlines() if line.strip()][-3:]
    return "\n".join(tail) or f"exit status {returncode}"


def pull(runner: Runner = subprocess.run) -> None:
    """Fetches the image once, so the parallel runs don't each start the same pull."""
    try:
        result = runner(["docker", "pull", "--quiet", MERMAID_CLI_IMAGE], capture_output=True, text=True, timeout=PULL_TIMEOUT, check=False)
    except _RUN_ERRORS as exc:
        raise DockerError(f"cannot pull {MERMAID_CLI_IMAGE}: {exc}") from exc
    if result.returncode != 0:
        reason = result.stderr.strip().splitlines()[-1:] or [f"exit status {result.returncode}"]
        raise DockerError(f"cannot pull {MERMAID_CLI_IMAGE}: {reason[0]}")


def render(block: Block, runner: Runner = subprocess.run) -> str | None:
    """None when the block renders, else the renderer's error message."""
    try:
        result = runner(RUN_ARGS, input=block.text, capture_output=True, text=True, timeout=BLOCK_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        return f"did not finish rendering within {BLOCK_TIMEOUT} seconds"
    except OSError as exc:
        raise DockerError(f"cannot run docker: {exc}") from exc
    if result.returncode in DOCKER_FAILED:
        raise DockerError(f"docker could not run {MERMAID_CLI_IMAGE} (exit status {result.returncode}): {result.stderr.strip()}")
    if result.returncode == 0:
        return None
    return error_message(result.returncode, result.stdout, result.stderr)


def tracked_markdown(root: Path) -> list[str]:
    listing = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--", "*.md"], capture_output=True, text=True, check=True).stdout
    return [name for name in listing.split("\0") if name]


def main(argv: list[str] | None = None, runner: Runner = subprocess.run) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", metavar="FILE", help="markdown files to check, relative to --root (default: every tracked .md file)")
    ap.add_argument("--root", type=Path, default=ROOT, help="repository root (tests point this at a temp repo)")
    args = ap.parse_args(argv)

    names = args.files or tracked_markdown(args.root)
    blocks = [block for name in names for block in find_blocks((args.root / name).read_text(encoding="utf-8"), name)]
    if not blocks:
        print("No Mermaid blocks to render.")
        return 0

    try:
        pull(runner)
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            messages = list(pool.map(lambda block: render(block, runner), blocks))
    except DockerError as exc:
        print(f"::error::{exc}")
        return 2

    failures = [(block, message) for block, message in zip(blocks, messages, strict=True) if message is not None]
    for block, message in failures:
        first, *rest = message.splitlines() or ["the renderer gave no message"]
        print(f"::error file={block.path},line={block.line}::{block.path}:{block.line}: {first}")
        for line in rest:
            print(f"  {line}")
    if failures:
        print(f"\n{len(failures)} of {len(blocks)} Mermaid blocks do not render.", file=sys.stderr)
        return 1
    print(f"All {len(blocks)} Mermaid blocks render.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
