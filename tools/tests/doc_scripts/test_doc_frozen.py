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
