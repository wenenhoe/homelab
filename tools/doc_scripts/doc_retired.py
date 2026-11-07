"""References to a retired decision number (ADR 0037 revision 4). Pure functions,
shared by check_retired_numbers.py.

A number is retired when its lineage was merged into another (it is that
lineage's `former_ids`) or demoted or dropped (it is listed in `removed.md`).
Nothing redirects it: a reference to it names a record that is not there, and
the link-target check does not see one written as text. This finds the three
shapes a reference takes:

- `ADR NNNN`, `ADR-NNNN`, and the numbers a list or range after `ADRs` names;
- a link whose visible number is retired, bare (`[NNNN](...)`) or with a name
  (`[ADR NNNN (Short name)](...)`), whatever its target;
- the same in a comment of code, a workflow or config, since every tracked
  text file is read.

What is not a reference: the ledger itself, a `former_ids` field, the
`Formerly ADR-...` the generated indexes print, and, in a markdown fence, the
hyphenated id (a schema example uses arbitrary ids). Tests of this tooling use
arbitrary numbers too and are not read.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from doc_scripts.doc_frontmatter import REVISION_PATH_RE, ROOT, load_lineages
from doc_scripts.doc_frozen import FROZEN_FIELDS, FROZEN_SECTIONS, HELD_STATUSES, split
from doc_scripts.doc_removed import LEDGER, ledger_numbers

EXCLUDE_PREFIXES = ("tools/tests/doc_scripts/",)

_NUMBER = r"(\d{4})(?!\d)"
_PROSE_RE = re.compile(r"\bADRs?([ -])" + _NUMBER)
_NEXT_RE = re.compile(r"(?:,\s*(?:(?:and|or)\s+)?|\s+(?:and|or|through|to)\s+|\s*[&/\u2013-]\s*)(?:ADRs?[ -])?" + _NUMBER)
_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]*?(?:^|/)(\d{4})-[a-z0-9-]+/revision-[^)\s]*?\.md)(?:#[^)]*)?\)")
_LINK_TEXT_NUMBER_RE = re.compile(r"(?<![\d./-])" + _NUMBER)
_FORMER_FIELD_RE = re.compile(r"^former_ids:[^\n]*(?:\n[ \t]*-[^\n]*)*", re.MULTILINE)
_FORMERLY_RE = re.compile(r"Formerly\s+ADR-\d{4}(?:,\s*ADR-\d{4})*")
_FENCE_RE = re.compile(r"^(```|~~~)[^\n]*\n.*?^\1[^\n]*$", re.DOTALL | re.MULTILINE)
_FIELD_RE = re.compile(rf"^(?:{'|'.join(FROZEN_FIELDS)}):[^\n]*(?:\n[ \t]+[^\n]*)*", re.MULTILINE)
_SECTION_RE = re.compile(rf"^## (?:{'|'.join(map(re.escape, FROZEN_SECTIONS))})[ \t]*\n.*?(?=^## |\Z)", re.DOTALL | re.MULTILINE)


@dataclass(frozen=True)
class Hit:
    offset: int  # of the retired number's first digit
    number: str
    line: int
    message: str
    frozen: bool = False
    listed: bool = False  # one of several numbers after `ADRs`, so a rewrite can leave the list reading wrong


def retired_numbers(root: Path = ROOT) -> dict[str, tuple[str, str | None]]:
    """number -> (what became of it, the live number that replaces it, or None).
    A number a lineage holds is never retired, whatever else says."""
    lineages = load_lineages(root)
    retired: dict[str, tuple[str, str | None]] = {}
    for number, (fate, where) in ledger_numbers(root).items():
        retired[number] = (f"{fate} ({where})", None)
    for lineage in lineages:
        for rev in lineage.revisions:
            for former in rev.fm.get("former_ids", []):
                retired[former[4:]] = (f"merged into ADR {lineage.number}", lineage.number)
    live = {lineage.number for lineage in lineages}
    return {n: v for n, v in retired.items() if n not in live}


def tracked_text_files(root: Path = ROOT) -> list[tuple[str, str]]:
    """(path relative to root, text) of every tracked or new file that is text,
    except the ledger and the doc tooling's own tests."""
    out = subprocess.run(["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard"], check=True, capture_output=True, text=True).stdout
    files = []
    for rel in sorted(set(out.splitlines())):
        if rel == f"docs/decisions/{LEDGER}" or rel.startswith(EXCLUDE_PREFIXES) or not (root / rel).is_file():
            continue
        try:
            files.append((rel, (root / rel).read_text(encoding="utf-8")))
        except UnicodeDecodeError:
            continue
    return files


def _spans(pattern: re.Pattern[str], text: str) -> list[tuple[int, int]]:
    return [m.span() for m in pattern.finditer(text)]


def _inside(offset: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= offset < end for start, end in spans)


def _frozen_spans(rel: str, text: str) -> list[tuple[int, int]]:
    if not REVISION_PATH_RE.search(rel) or split(text)[0].get("status") not in HELD_STATUSES:
        return []
    return _spans(_FIELD_RE, text) + _spans(_SECTION_RE, text)


def find_hits(rel: str, text: str, retired: dict[str, tuple[str, str | None]]) -> list[Hit]:
    """Every reference in one file to a retired number, in file order. A link is read
    before the plain text, so a name inside a link's text is reported once, as the link."""
    if not retired or not re.search(r"\d{4}", text):
        return []
    skip = _spans(_FORMER_FIELD_RE, text) + _spans(_FORMERLY_RE, text)
    fences = _spans(_FENCE_RE, text) if rel.endswith(".md") else []
    frozen = _frozen_spans(rel, text)
    found: dict[int, Hit] = {}

    def add(offset: int, number: str, message: str, listed: bool = False) -> None:
        if number in retired and offset not in found and not _inside(offset, skip):
            found[offset] = Hit(offset, number, text.count("\n", 0, offset) + 1, message, _inside(offset, frozen), listed)

    for m in _LINK_RE.finditer(text):
        for t in _LINK_TEXT_NUMBER_RE.finditer(m.group(1)):
            add(m.start(1) + t.start(1), t.group(1), f"link text names ADR {t.group(1)}, which was {{fate}}; the link goes to ADR {m.group(3)}")
    for m in _PROSE_RE.finditer(text):
        numbers = [(m.start(2), m.group(2), not (m.group(1) == "-" and _inside(m.start(), fences)))]
        pos = m.end(2)
        while n := _NEXT_RE.match(text, pos):
            numbers.append((n.start(1), n.group(1), True))
            pos = n.end(1)
        for offset, number, reported in numbers:
            if reported:
                add(offset, number, f"names ADR {number}, which was {{fate}}", listed=len(numbers) > 1)
    return [
        Hit(h.offset, h.number, h.line, h.message.format(fate=retired[h.number][0]), h.frozen, h.listed) for h in sorted(found.values(), key=lambda h: h.offset)
    ]


def advice(number: str, retired: dict[str, tuple[str, str | None]]) -> str:
    replacement = retired[number][1]
    return f"name ADR {replacement}" if replacement else "point at where it went, or drop the mention"


def retired_reference_errors(root: Path = ROOT) -> list[str]:
    retired = retired_numbers(root)
    errors = []
    for rel, text in tracked_text_files(root):
        for hit in find_hits(rel, text, retired):
            error = f"{rel}:{hit.line}: {hit.message}; {advice(hit.number, retired)}"
            if hit.frozen:
                error += (
                    f". This is a frozen section of an accepted revision: make the fix in a commit with an `Editorial-Fix: {rel}` trailer, "
                    "or the accepted-records check fails the pull request"
                )
            errors.append(error)
    return errors
