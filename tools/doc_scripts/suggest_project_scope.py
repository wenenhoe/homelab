#!/usr/bin/env python3
"""Suggests what a project's `allowed_paths` should hold and what it is missing, from the files
the project's PRs edit, the one that closes it included. It looks where those files are named
instead of where the author remembers them:

  named    paths the project doc says it will change: its Scope (without "Not in"), Execution
           plan and Acceptance criteria sections
  closing  files the closing PR edits: every file that names the project doc, and the NIST
           alignment page when it links a revision the close supersedes
  sweep    every tracked file that mentions a --sweep TERM (a name the project removes, renames
           or reshapes), outside decision history, for the author to put in scope or under
           "Not in"

Advisory: prints and exits 0. It reads the project doc and the tree as they stand now, not the
base, since it is meant for writing the scope. docs/projects/README.md#scope says what the scope
is for.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from doc_scripts.doc_frontmatter import ROOT, read_frontmatter
from doc_scripts.doc_scope import IMPLICIT_PATTERNS, PROJECT_DOC_RE, glob_to_regex, lifecycle_paths

NIST_PAGE = "docs/topics/engineering/nist-800-53-alignment.md"
CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
LINK_RE = re.compile(r"\]\(([^)\s#]+)(?:#[^)\s]*)?\)")


@dataclass(frozen=True)
class Finding:
    entry: str  # the allowed_paths entry that would cover `files`
    files: tuple[str, ...]
    why: str


@dataclass
class Report:
    doc: str
    project_id: str
    allowed: list[str]
    exempt: dict[str, str]
    named: list[Finding] = field(default_factory=list)
    closing: list[Finding] = field(default_factory=list)
    sweep: dict[str, list[Finding]] = field(default_factory=dict)

    def proposed(self) -> list[str]:
        """Today's entries plus the named and closing ones that no other new entry already covers.
        Sweep hits wait for the author's call."""
        new = list(dict.fromkeys(f.entry for f in [*self.named, *self.closing]))
        for entry in list(new):
            if any(other != entry and glob_to_regex(other).match(entry) for other in new):
                new.remove(entry)
        return [*self.allowed, *new]


def run_git(root: Path, *args: str) -> str:
    """Stdout of a git command. Exit 1 is `git grep` finding nothing; any other failure stops."""
    done = subprocess.run(["git", "-C", str(root), *args], check=False, capture_output=True, text=True)
    if done.returncode > 1:
        raise SystemExit(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


def nul_list(root: Path, *args: str) -> list[str]:
    return [item for item in run_git(root, *args).split("\0") if item]


def count_hits(root: Path, term: str) -> dict[str, int]:
    """Tracked files that mention `term`, ignoring case, with how many lines do."""
    lines = run_git(root, "grep", "-c", "--null", "-I", "-i", "-F", "-e", term).split("\n")
    return {path: int(count) for path, _, count in (line.rpartition("\0") for line in lines) if path}


def section(text: str, heading: str) -> str:
    m = re.search(rf"^## {re.escape(heading)}[ \t]*\n(.*?)(?=^## |\Z)", text, re.DOTALL | re.MULTILINE)
    return m.group(1) if m else ""


def stated_changes(text: str) -> str:
    """The parts of a project doc that say what it changes: Scope without its "Not in" paragraph, the
    Execution plan and the Acceptance criteria. Agent handoff and Risks also name files the project only reads."""
    scope = re.sub(r"^Not in:.*?(?:\n\s*\n|\Z)", "", section(text, "Scope"), flags=re.DOTALL | re.MULTILINE)
    return "\n".join([scope, section(text, "Execution plan"), section(text, "Acceptance criteria")])


def named_patterns(text: str, doc: str) -> list[str]:
    """Repo-relative path patterns the text names: code spans holding a `/` and relative link targets."""
    found = []
    for span in CODE_SPAN_RE.findall(text):
        span = span.partition("#")[0].removeprefix("./")
        if "/" in span and not re.search(r"\s", span) and not span.startswith(("/", "~", "http")):
            found.append(span)
    for target in LINK_RE.findall(text):
        if "://" not in target and not target.startswith(("/", "mailto:")):
            resolved = os.path.normpath(os.path.join(os.path.dirname(doc), target)).replace(os.sep, "/")
            if not resolved.startswith(".."):
                found.append(resolved)
    return list(dict.fromkeys(found))


def files_named(pattern: str, tracked: list[str]) -> list[str]:
    """Tracked files a path pattern names: the file itself, everything under a directory, or a glob's matches."""
    bare = pattern.rstrip("/")
    glob = glob_to_regex(bare) if re.search(r"[*?]", bare) else None
    return [f for f in tracked if f == bare or f.startswith(bare + "/") or (glob and glob.match(f))]


def entry_for(pattern: str, tracked: list[str]) -> str:
    """The allowed_paths entry for a named pattern: a file or glob as written, a directory as `dir/**`."""
    bare = pattern.rstrip("/")
    return bare if bare in tracked or re.search(r"[*?]", bare) else f"{bare}/**"


def build_report(root: Path, doc: str, terms: list[str]) -> Report:
    fm = read_frontmatter(root / doc)
    allowed = list(fm.get("allowed_paths") or [])
    exempt = lifecycle_paths(fm, lambda path: read_frontmatter(root / path), root)
    tracked = nul_list(root, "ls-files", "-z")
    patterns = [glob_to_regex(p) for p in [*allowed, *IMPLICIT_PATTERNS]]

    def covered(path: str) -> bool:
        return path in exempt or any(p.match(path) for p in patterns)

    def in_history(path: str) -> bool:
        return path == doc or path.startswith("docs/decisions/")

    report = Report(doc, fm["id"], allowed, exempt)

    stated = stated_changes((root / doc).read_text(encoding="utf-8"))
    for pattern in named_patterns(stated, doc):
        missing = tuple(f for f in files_named(pattern, tracked) if not in_history(f) and not covered(f))
        if missing:
            count = f"{len(missing)} files; " if len(missing) > 1 else ""
            report.named.append(Finding(entry_for(pattern, tracked), missing, f"{count}named in the doc as `{pattern}`"))

    for path in nul_list(root, "grep", "-l", "--null", "-I", "-F", "-e", f"projects/{Path(doc).name}"):
        if path != doc and not covered(path):
            report.closing.append(Finding(path, (path,), "names this project doc, so closing it edits this file"))

    nist = root / NIST_PAGE
    if nist.is_file() and not covered(NIST_PAGE):
        page = nist.read_text(encoding="utf-8")
        for old in (path for path, why in exempt.items() if why == "superseded"):
            name = f"{Path(old).parent.name}/{Path(old).name}"
            if name in page:
                why = f"links `{name}`, which the close supersedes; the drift check fails until it names the successor"
                report.closing.append(Finding(NIST_PAGE, (NIST_PAGE,), why))
                break

    for term in dict.fromkeys(terms):
        hits = count_hits(root, term)
        report.sweep[term] = [
            Finding(path, (path,), f"{n} line{'s' if n != 1 else ''}") for path, n in hits.items() if not in_history(path) and not covered(path)
        ]
    return report


def render(report: Report) -> str:
    def block(title: str, lines: list[str]) -> list[str]:
        return [title, *(f"  {line}" for line in lines or ["none"]), ""]

    def lines_of(findings: list[Finding]) -> list[str]:
        return [f"{f.entry}  ({f.why})" for f in findings]

    out = [f"{report.project_id} ({report.doc}): {len(report.allowed)} allowed_paths entries today", ""]
    out += block("Exempt without an entry", [f"{path}  ({why})" for path, why in report.exempt.items()])
    out += block("Named by the project doc, not covered", lines_of(report.named))
    out += block("Edited by the closing PR, not covered", lines_of(report.closing))
    for term, findings in report.sweep.items():
        out += block(f'Mention "{term}", not covered: put each in scope or under "Not in"', lines_of(findings))
    out += ["allowed_paths with the named and closing entries added:", "  allowed_paths:", *(f"    - {entry}" for entry in report.proposed()), ""]
    out.append("Not detected: a new topic doc needs a row in docs/topics/README.md, which no scope exempts.")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", help="the project doc's file name, with or without .md, or its path from the repository root")
    ap.add_argument("--sweep", action="append", default=[], metavar="TERM", help="a name the project removes, renames or reshapes; repeatable")
    ap.add_argument("--root", type=Path, default=ROOT, help="repository root (tests point this at a temp repo)")
    args = ap.parse_args(argv)

    doc = f"docs/projects/{Path(args.project).name.removesuffix('.md')}.md"
    if "/" in args.project and not args.project.endswith(doc):
        ap.error(f"{args.project} is not a project doc under docs/projects/")
    if not PROJECT_DOC_RE.fullmatch(doc) or not (args.root / doc).is_file():
        ap.error(f"{doc} does not exist")
    if any(not term.strip() for term in args.sweep):
        ap.error("--sweep needs a non-empty term")

    print(render(build_report(args.root, doc, args.sweep)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
