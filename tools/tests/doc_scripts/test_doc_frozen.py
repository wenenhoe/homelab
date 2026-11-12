"""Unit tests for doc_frozen.py - which edits to an accepted revision count as
changing what it decided. Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import pytest
from doc_scripts import doc_frozen as frozen

PATH = "docs/decisions/0001-x/revision-000.md"


def doc(status="accepted", solution="Use a proxy", decision="Run a proxy.", context="How it was found.", **sections):
    parts = {
        "Problem": "A problem.",
        "Context": context,
        "Decision": decision,
        "Consequences": "Costs a port.",
        "Invariants": "Nothing is exposed.",
        "Non-goals": "Not a firewall.",
        "Validation": "A test.",
        "Reconsideration triggers": "A new transport.",
    }
    parts.update(sections)
    body = "".join(f"## {name}\n\n{text}\n\n" for name, text in parts.items())
    return f'---\nid: ADR-0001\ntitle: "Proxying"\nsolution: "{solution}"\nstatus: {status}\n---\n\n# 0001. Proxying\n\n{body}'


def errors(base, head, editorial=()):
    return frozen.frozen_errors([(PATH, base, head)], set(editorial))


class TestWhatIsFrozen:
    def test_identical_text_is_clean(self):
        assert errors(doc(), doc()) == []

    @pytest.mark.parametrize("name", ["Context", "Consequences", "Validation"])
    def test_the_other_sections_may_be_cut(self, name):
        assert errors(doc(), doc(**{name: "Shorter."})) == []

    def test_a_section_may_be_removed_if_it_is_not_frozen(self):
        head = doc().replace("## Validation\n\nA test.\n\n", "")
        assert errors(doc(), head) == []

    def test_a_declared_reliance_may_be_added_to_an_accepted_revision(self):
        head = doc().replace("status: accepted", 'status: accepted\nrelies_on:\n  - adr: ADR-0002\n    reason: "It presupposes the proxy boundary."')
        assert errors(doc(), head) == []

    @pytest.mark.parametrize("name", ["Problem", "Decision", "Invariants", "Non-goals", "Reconsideration triggers"])
    def test_a_frozen_section_may_not_change(self, name):
        [error] = errors(doc(), doc(**{name: "Something else."}))
        assert PATH in error
        assert f"## {name}" in error

    def test_deleting_a_frozen_section_is_a_change(self):
        head = doc().replace("## Invariants\n\nNothing is exposed.\n\n", "")
        [error] = errors(doc(), head)
        assert "## Invariants" in error

    def test_the_title_and_solution_are_frozen_too(self):
        [error] = errors(doc(), doc(solution="Use something else"))
        assert "solution:" in error

    def test_frontmatter_metadata_may_change(self):
        head = doc().replace("status: accepted", "status: superseded\nsuperseded_by: 1")
        assert errors(doc(), head) == []


class TestEditorialEditsAreNotChanges:
    def test_a_link_target_may_be_corrected(self):
        base = doc(decision="See [the doc](../old/path.md).")
        assert errors(base, doc(decision="See [the doc](../new/path.md).")) == []

    def test_a_moved_file_note_may_be_inserted(self):
        base = doc(decision="Edit `ansible/a.py` first.")
        assert errors(base, doc(decision="Edit `ansible/a.py` (renamed: `tools/a.py`) first.")) == []
        assert errors(base, doc(decision="Edit `ansible/a.py` (removed) first.")) == []
        assert errors(base, doc(decision="Edit `ansible/a.py` (removed; replaced by: `b.py`) first.")) == []

    def test_a_short_name_may_be_added_to_a_link(self):
        base = doc(decision="Per [ADR 0044](../0044/revision-000.md).")
        head = doc(decision="Per [ADR 0044 (CD agent trigger)](../0044/revision-000.md).")
        assert errors(base, head) == []

    def test_whitespace_reflow_is_not_a_change(self):
        assert errors(doc(decision="One line of text."), doc(decision="One\nline   of\ntext.")) == []

    def test_a_real_wording_change_is_still_caught_next_to_a_link(self):
        base = doc(decision="Run [it](a.md) now.")
        assert len(errors(base, doc(decision="Run [it](b.md) later."))) == 1


class TestWhoIsHeld:
    @pytest.mark.parametrize("status", ["working", "approved", "abandoned", "retired"])
    def test_only_accepted_and_superseded_revisions_are_held(self, status):
        assert errors(doc(status=status), doc(status=status, decision="Changed.")) == []

    def test_a_superseded_revision_is_held(self):
        assert len(errors(doc(status="superseded"), doc(status="superseded", decision="Changed."))) == 1

    def test_a_declared_editorial_fix_excuses_the_path(self):
        assert errors(doc(), doc(decision="Fixed typo."), editorial={PATH}) == []
        assert len(errors(doc(), doc(decision="Fixed typo."), editorial={"docs/decisions/0002-y/revision-000.md"})) == 1


class TestCondenseSuperseded:
    def test_it_keeps_only_the_frozen_sections(self):
        condensed = frozen.condense_superseded(doc(status="superseded"))
        assert [h for h in ("Context", "Consequences", "Validation") if f"## {h}" in condensed] == []
        assert all(f"## {h}" in condensed for h in frozen.FROZEN_SECTIONS)

    def test_what_it_keeps_is_what_the_frozen_check_reads(self):
        text = doc(status="superseded")
        assert frozen.frozen_view(frozen.condense_superseded(text)) == frozen.frozen_view(text)
        assert errors(text, frozen.condense_superseded(text)) == []

    def test_the_frontmatter_and_title_are_untouched(self):
        condensed = frozen.condense_superseded(doc(status="superseded"))
        assert condensed.startswith('---\nid: ADR-0001\ntitle: "Proxying"')
        assert "# 0001. Proxying" in condensed

    def test_it_is_idempotent(self):
        once = frozen.condense_superseded(doc(status="superseded"))
        assert frozen.condense_superseded(once) == once

    def test_a_revision_without_a_problem_section_keeps_what_it_has(self):
        text = doc(status="superseded").replace("## Problem\n\nA problem.\n\n", "")
        condensed = frozen.condense_superseded(text)
        assert "## Problem" not in condensed
        assert "## Decision" in condensed

    def test_a_heading_inside_a_code_fence_is_not_a_section(self):
        decision = "Run it.\n\n```sh\n## not a heading\nls\n```"
        condensed = frozen.condense_superseded(doc(status="superseded", decision=decision))
        assert "## not a heading" in condensed
        assert frozen.surplus_sections(decision) == []

    def test_a_diagram_in_the_decision_stays_with_it(self):
        decision = "Run it.\n\n```mermaid\nflowchart LR\n  a --> b\n```"
        assert "a --> b" in frozen.condense_superseded(doc(status="superseded", decision=decision))

    def test_surplus_sections_names_each_other_heading(self):
        body = frozen.split(doc())[1]
        assert frozen.surplus_sections(body) == ["Context", "Consequences", "Validation"]
