"""The frozen sections of an accepted decision revision (ADR 0037 revision 4).
Pure functions, shared by check_accepted_records.py.

An `accepted` or `superseded` revision may be shortened in place if what it
decided is unchanged: its title, its one-line solution, and its Problem,
Decision, Invariants, Non-goals and Reconsideration triggers sections. Context
narration, Consequences, Validation and the rest may be cut; a `superseded` revision
must have them cut and keeps only the frozen sections (`surplus_sections`). Editorial fixes
the decisions README allows inside those sections (a link target, a moved-file
note, a short name in a link's text) do not count as a change.
"""

from __future__ import annotations

import re

import yaml

FROZEN_SECTIONS = ("Problem", "Decision", "Invariants", "Non-goals", "Reconsideration triggers")
FROZEN_FIELDS = ("title", "solution")
# Revisions in these states on the base are held to the rule.
HELD_STATUSES = {"accepted", "superseded"}

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
_LINK_TARGET_RE = re.compile(r"\]\([^)]*\)")
_MOVED_NOTE_RE = re.compile(r"\s*\((?:renamed: [^)]+|removed(?:; replaced by: [^)]+)?)\)")
_SHORT_NAME_RE = re.compile(r"(\[ADR\s+\d{4}(?:\s+revision\s+[\w-]+)?)\s+\([^()\]]+\)\]")


def split(text: str) -> tuple[dict, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    return yaml.safe_load(m.group(1)) or {}, m.group(2)


def normalise(text: str) -> str:
    """Drops what the README lets an edit change in any state, then collapses whitespace."""
    text = _LINK_TARGET_RE.sub("]", text)
    text = _MOVED_NOTE_RE.sub("", text)
    text = _SHORT_NAME_RE.sub(r"\1]", text)
    return " ".join(text.split())


def section(body: str, heading: str) -> str | None:
    m = re.search(rf"^## {re.escape(heading)}[ \t]*\n(.*?)(?=^## |\Z)", body, re.DOTALL | re.MULTILINE)
    return normalise(m.group(1)) if m else None


def frozen_view(text: str) -> dict[str, str | None]:
    fm, body = split(text)
    view: dict[str, str | None] = {f"{field}:": normalise(str(fm.get(field, ""))) for field in FROZEN_FIELDS}
    for heading in FROZEN_SECTIONS:
        view[f"## {heading}"] = section(body, heading)
    return view


def changed_parts(base_text: str, head_text: str) -> list[str]:
    """Names of the frozen parts that differ between two texts of one revision."""
    before, after = frozen_view(base_text), frozen_view(head_text)
    return [name for name in before if before[name] != after[name]]


def _split_sections(body: str) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """The lines before the first `## ` heading, then each section as (heading, its lines,
    heading included). A `## ` line inside a fenced code block is not a heading."""
    preamble: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    fenced = False
    for line in body.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        heading = None if fenced else re.match(r"## (.+?)[ \t]*$", line)
        if heading:
            sections.append((heading.group(1), [line]))
        elif sections:
            sections[-1][1].append(line)
        else:
            preamble.append(line)
    return preamble, sections


def surplus_sections(body: str) -> list[str]:
    """The `## ` headings of a revision that a superseded one may not keep."""
    return [name for name, _ in _split_sections(body)[1] if name not in FROZEN_SECTIONS]


def condense_superseded(text: str) -> str:
    """The text of a superseded revision cut to what it keeps: its frontmatter, its title heading and
    the frozen sections, each as written. What was current in it is carried by its successor."""
    m = _FRONTMATTER_RE.match(text)
    head, body = (f"---\n{m.group(1)}\n---\n", m.group(2)) if m else ("", text)
    preamble, sections = _split_sections(body)
    chunks = ["\n".join(preamble).strip("\n")]
    chunks += ["\n".join(lines).strip("\n") for name, lines in sections if name in FROZEN_SECTIONS]
    return head + "\n" + "\n\n".join(c for c in chunks if c) + "\n"


def frozen_errors(changes: list[tuple[str, str, str]], editorial: set[str]) -> list[str]:
    """`changes` are (path, base text, head text) for revisions that exist on both sides; only
    the ones whose base status is held are judged. `editorial` are the paths a commit declared
    an editorial fix with an `Editorial-Fix:` trailer."""
    errors = []
    for path, base_text, head_text in changes:
        if split(base_text)[0].get("status") not in HELD_STATUSES or path in editorial:
            continue
        parts = changed_parts(base_text, head_text)
        if parts:
            errors.append(
                f"{path}: changes {', '.join(parts)}, which an accepted revision keeps fixed — write a new revision. "
                "A typo or wrong fact that was wrong at the time is an editorial fix: say so with an `Editorial-Fix: <path>` trailer on a commit of the change"
            )
    return errors
