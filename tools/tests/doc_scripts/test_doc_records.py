"""Unit tests for doc_records.py: the service-record rules of ADR 0100 (the sections, the link from
the catalog and the exemption list). Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from _doc_fixtures import assert_one_error
from doc_scripts import doc_records as records
from utils.app_catalog import CATALOG_RELATIVE, load_catalog

DOC = "docs/topics/services/web.md"


def record(*, skip: tuple[str, ...] = (), empty: tuple[str, ...] = (), order: tuple[str, ...] = records.SECTIONS, extra: str = "") -> str:
    """A record whose sections are all filled; `skip` leaves one out, `empty` leaves its body blank, `order` sets the sequence."""
    out = ["# Web", "", "What it is.", ""]
    for name in order:
        if name in skip:
            continue
        out += [f"## {name}", ""]
        if name not in empty:
            out += [f"The {name.lower()} of web.", ""]
    return "\n".join(out) + extra


class Tree:
    def __init__(self, root: Path) -> None:
        self.root = root

    def catalog(self, **apps: dict) -> None:
        path = self.root / CATALOG_RELATIVE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump({"app_catalog": apps}, sort_keys=False), encoding="utf-8")

    def doc(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def errors(self, exempt: tuple[str, ...] = ()) -> list[str]:
        return records.record_errors(self.root, exempt)


@pytest.fixture
def tree(root: Path) -> Tree:
    return Tree(root)


class TestSections:
    def test_a_record_with_every_section_filled_passes(self):
        assert records.section_errors(record()) == []

    @pytest.mark.parametrize("name", records.SECTIONS)
    def test_a_missing_section_is_named(self, name):
        [error] = records.section_errors(record(skip=(name,)))
        assert error.startswith("lacks the section(s)")
        assert f"'{name}'" in error.split(";")[0]

    def test_every_missing_section_is_named_at_once(self):
        [error] = records.section_errors(record(skip=("Data", "Lifecycle")))
        assert "'Data', 'Lifecycle'" in error

    @pytest.mark.parametrize("name", records.SECTIONS)
    def test_an_empty_section_is_named(self, name):
        [error] = records.section_errors(record(empty=(name,)))
        assert f"the section '{name}' is empty" in error

    def test_sections_out_of_order_fail(self):
        order = ("Data", "Dependencies", *records.SECTIONS[2:])
        assert_one_error(records.section_errors(record(order=order)), "out of order")

    def test_a_repeated_section_fails(self):
        assert_one_error(records.section_errors(record(extra="\n## Data\n\nAgain.\n")), "'Data' more than once")

    def test_other_sections_between_the_required_ones_are_allowed(self):
        text = record().replace("## Exposure", "## Background\n\nWhy it exists.\n\n## Exposure")
        assert records.section_errors(text) == []

    def test_a_section_may_say_it_does_not_apply_or_that_a_fact_is_unknown(self):
        text = (
            record(empty=("Exposure", "Data"))
            .replace("## Exposure\n", "## Exposure\n\nNone: it has no listener.\n")
            .replace("## Data\n", "## Data\n\nUnknown: what the volume holds.\n")
        )
        assert records.section_errors(text) == []

    def test_a_subheading_alone_does_not_fill_a_section(self):
        text = record(empty=("Lifecycle",)).replace("## Lifecycle\n", "## Lifecycle\n\n### Upgrade\n")
        assert_one_error(records.section_errors(text), "'Lifecycle' is empty")

    def test_a_subheading_with_text_fills_a_section(self):
        text = record(empty=("Lifecycle",)).replace("## Lifecycle\n", "## Lifecycle\n\n### Upgrade\n\nPull the new tag.\n")
        assert records.section_errors(text) == []

    def test_a_fenced_command_fills_a_section(self):
        text = record(empty=("Observability",)).replace("## Observability\n", "## Observability\n\n```sh\ncurl -f http://web/health\n```\n")
        assert records.section_errors(text) == []

    def test_a_heading_inside_a_fence_is_not_a_section(self):
        fenced = "\n```md\n## Lifecycle\n\nnot a heading\n```\n"
        assert_one_error(records.section_errors(record(skip=("Lifecycle",), extra=fenced)), "'Lifecycle'")

    def test_a_heading_with_trailing_hashes_and_spaces_still_counts(self):
        assert records.section_errors(record().replace("## Threat model", "##   Threat model  ##")) == []

    def test_a_different_case_is_a_different_section(self):
        assert_one_error(records.section_errors(record().replace("## Threat model", "## Threat Model")), "'Threat model'")

    def test_a_level_three_heading_is_not_a_section(self):
        errors = records.section_errors(record().replace("## Lifecycle", "### Lifecycle"))
        assert any("lacks the section(s) 'Lifecycle'" in e for e in errors)


class TestCatalogLink:
    def test_an_app_with_a_complete_record_passes(self, tree):
        tree.catalog(web={"doc": DOC})
        tree.doc(DOC, record())
        assert tree.errors() == []

    def test_an_app_with_no_doc_fails_with_what_to_do(self, tree):
        tree.catalog(web={})
        assert_one_error(tree.errors(), "web has no `doc:`", "Write the record", "takes no new ones")

    def test_an_exempt_app_with_no_doc_passes(self, tree):
        tree.catalog(web={})
        assert tree.errors(exempt=("web",)) == []

    def test_an_app_with_a_record_that_is_still_exempt_fails(self, tree):
        tree.catalog(web={"doc": DOC})
        tree.doc(DOC, record())
        assert_one_error(tree.errors(exempt=("web",)), "web names a record but is still on the exemption list")

    def test_an_exemption_for_an_app_not_in_the_catalog_fails(self, tree):
        tree.catalog(web={"doc": DOC})
        tree.doc(DOC, record())
        assert_one_error(tree.errors(exempt=("gone",)), "names gone, which isn't an app in the catalog")

    def test_a_doc_that_does_not_exist_fails(self, tree):
        tree.catalog(web={"doc": DOC})
        assert_one_error(tree.errors(), f"web names {DOC}, which doesn't exist")

    def test_a_record_with_a_missing_section_is_reported_against_the_record(self, tree):
        tree.catalog(web={"doc": DOC})
        tree.doc(DOC, record(skip=("Data",)))
        assert_one_error(tree.errors(), f"{DOC}: lacks the section(s) 'Data'")

    def test_entries_naming_one_record_read_it_once(self, tree):
        tree.catalog(hub={"doc": DOC}, agent={"doc": DOC})
        tree.doc(DOC, record(empty=("Data",)))
        assert_one_error(tree.errors(), "'Data' is empty")

    @pytest.mark.parametrize("doc", ["/etc/passwd", "docs/topics/../../x.md", ["a"], 3, True], ids=["absolute", "dotdot", "list", "number", "bool"])
    def test_a_malformed_doc_is_left_to_the_catalog_rules(self, tree, doc):
        tree.catalog(web={"doc": doc})
        assert tree.errors() == []

    def test_a_missing_catalog_is_an_error_not_a_pass(self, tree):
        [error] = tree.errors()
        assert "can't read" in error

    def test_errors_follow_catalog_order(self, tree):
        tree.catalog(b={}, a={})
        assert [e.split()[1] for e in tree.errors()] == ["b", "a"]


class TestTheRealRepository:
    def test_every_catalog_app_has_a_record_or_is_exempt(self):
        assert records.record_errors() == []

    def test_the_exemption_list_has_no_repeats(self):
        assert len(set(records.EXEMPT_APPS)) == len(records.EXEMPT_APPS)

    def test_the_exemption_list_is_the_apps_that_have_no_record(self):
        catalog = load_catalog()
        assert sorted(name for name, app in catalog.items() if "doc" not in app) == sorted(records.EXEMPT_APPS)

    def test_the_sections_are_the_ones_the_decision_names(self):
        assert records.SECTIONS == ("Dependencies", "Data", "Exposure", "Threat model", "Observability", "Disaster recovery", "Lifecycle")


def test_the_project_template_has_one_readiness_line_per_section_in_order() -> None:
    from doc_scripts.doc_frontmatter import ROOT

    template = (ROOT / "docs/projects/TEMPLATE.md").read_text(encoding="utf-8")
    lines = [line for line in template.splitlines() if line.startswith("- [ ] `")]
    assert [line.split("`")[1] for line in lines] == list(records.SECTIONS)
