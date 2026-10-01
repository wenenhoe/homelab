"""Unit tests for the decision-lineage-aware parts of
check_doc_drift.py: index coverage of lineage directories, relative
links to non-markdown files, and the NIST-link supersession check.
Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _doc_fixtures import revision
from doc_scripts import check_doc_drift as drift

INDEX_DIRS = ("docs", "docs/decisions", "docs/architecture", "docs/projects")


class TmpRepo:
    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, rel: str, text: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


@pytest.fixture
def repo(root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(drift, "ROOT", root)
    drift.errors.clear()
    yield TmpRepo(root)
    drift.errors.clear()


class TestLineageIndex:
    @pytest.fixture(autouse=True)
    def _index_readmes(self, repo):
        for d in INDEX_DIRS:
            repo.write(f"{d}/README.md", "# Index\n")

    def test_lineage_directory_must_appear_in_the_decisions_index(self, repo):
        revision(repo.root, "0013-secret-storage", 0)
        drift.check_doc_indexes()
        assert len(drift.errors) == 1, drift.errors
        assert "lineage 0013-secret-storage/ exists but isn't linked" in drift.errors[0]

    def test_linked_lineage_directory_passes(self, repo):
        revision(repo.root, "0013-secret-storage", 0)
        repo.write("docs/decisions/README.md", "# Index\n\n[0013](0013-secret-storage/revision-000.md)\n")
        drift.check_doc_indexes()
        assert drift.errors == []


class TestRecursiveIndex:
    """A recursive INDEXED_DOC_DIRS entry covers nested folders and matches
    each doc by its path relative to the index, not by bare filename."""

    @pytest.fixture(autouse=True)
    def _indexed_dirs(self, repo, monkeypatch):
        monkeypatch.setattr(drift, "INDEXED_DOC_DIRS", (("", False), ("topics", True)))
        repo.write("docs/README.md", "# Docs\n")

    def test_nested_doc_missing_from_the_index_fails_by_relative_path(self, repo):
        repo.write("docs/topics/README.md", "# Topics\n")
        repo.write("docs/topics/dev/ci/overview.md", "# CI\n")
        drift.check_doc_indexes()
        assert len(drift.errors) == 1, drift.errors
        assert "dev/ci/overview.md exists but isn't linked" in drift.errors[0]

    def test_nested_doc_linked_by_relative_path_passes(self, repo):
        repo.write("docs/topics/README.md", "[CI](dev/ci/overview.md) [Tests](dev/molecule.md)\n")
        repo.write("docs/topics/dev/ci/overview.md", "# CI\n")
        repo.write("docs/topics/dev/molecule.md", "# Molecule\n")
        drift.check_doc_indexes()
        assert drift.errors == []

    def test_same_filename_in_two_folders_needs_each_to_be_linked(self, repo):
        repo.write("docs/topics/README.md", "[A](a/overview.md)\n")
        repo.write("docs/topics/a/overview.md", "# A\n")
        repo.write("docs/topics/b/overview.md", "# B\n")
        drift.check_doc_indexes()
        assert len(drift.errors) == 1, drift.errors
        assert "b/overview.md exists but isn't linked" in drift.errors[0]

    @pytest.mark.parametrize("name", ["README.md", "TEMPLATE.md"], ids=["readme", "template"])
    def test_nested_readmes_and_templates_are_exempt(self, repo, name):
        repo.write("docs/topics/README.md", "# Topics\n")
        repo.write(f"docs/topics/dev/{name}", "# Exempt\n")
        drift.check_doc_indexes()
        assert drift.errors == []

    def test_non_recursive_directory_ignores_nested_folders(self, repo):
        repo.write("docs/topics/README.md", "# Topics\n")
        repo.write("docs/nested/other.md", "# not indexed by docs/README.md\n")
        drift.check_doc_indexes()
        assert drift.errors == []


class TestCrossFolderLink:
    @pytest.fixture(autouse=True)
    def _sibling_docs(self, repo):
        repo.write("docs/topics/services/openbao.md", "# OpenBao\n\n## Unsealing\n")

    def test_relative_link_into_a_sibling_folder_resolves(self, repo):
        repo.write("docs/topics/secrets/rotation.md", "See [OpenBao](../services/openbao.md#unsealing).\n")
        drift.check_no_stale_anchors()
        assert drift.errors == []

    @pytest.mark.parametrize(
        ("link", "reported"),
        [
            ("../services/openbao.md#sealing", "#sealing"),
            ("../services/gone.md", "../services/gone.md"),
        ],
        ids=["wrong-anchor", "dangling-file"],
    )
    def test_a_broken_cross_folder_link_fails(self, repo, link, reported):
        repo.write("docs/topics/secrets/rotation.md", f"See [x]({link}).\n")
        drift.check_no_stale_anchors()
        assert len(drift.errors) == 1, drift.errors
        assert reported in drift.errors[0]


class TestRepoFileLink:
    def test_relative_link_to_an_existing_config_file_passes(self, repo):
        repo.write("docker/openbao/policy.hcl", "path {}\n")
        repo.write("docs/decisions/0001-x/revision-000.md", "See [policy](../../../docker/openbao/policy.hcl).\n")
        drift.check_no_stale_anchors()
        assert drift.errors == []

    def test_relative_link_to_a_missing_file_fails(self, repo):
        repo.write("docs/decisions/0001-x/revision-000.md", "See [policy](../../docker/openbao/policy.hcl).\n")
        drift.check_no_stale_anchors()
        assert len(drift.errors) == 1, drift.errors
        assert "../../docker/openbao/policy.hcl" in drift.errors[0]

    def test_template_placeholders_are_skipped(self, repo):
        repo.write("docs/decisions/TEMPLATE.md", "[x](../nowhere/file.yaml)\n")
        drift.check_no_stale_anchors()
        assert drift.errors == []


class TestNistAlignment:
    def test_link_to_a_superseded_lineage_revision_fails(self, repo):
        revision(repo.root, "0013-secret-storage", 0, status="superseded", superseded_by=1)
        revision(repo.root, "0013-secret-storage", 1, status="accepted", supersedes=0)
        repo.write("docs/nist-800-53-alignment.md", "[old](decisions/0013-secret-storage/revision-000.md)\n")
        drift.check_nist_alignment_currency()
        assert len(drift.errors) == 1, drift.errors
        assert "now status: superseded" in drift.errors[0]

    def test_link_to_the_accepted_revision_passes(self, repo):
        revision(repo.root, "0013-secret-storage", 0, status="superseded", superseded_by=1)
        revision(repo.root, "0013-secret-storage", 1, status="accepted", supersedes=0)
        repo.write("docs/nist-800-53-alignment.md", "[now](decisions/0013-secret-storage/revision-001.md)\n")
        drift.check_nist_alignment_currency()
        assert drift.errors == []

    def test_links_outside_lineages_are_ignored(self, repo):
        repo.write("docs/decisions/0001-flat.md", "# not a lineage\n")
        repo.write("docs/host-vars.md", "# Host vars\n")
        repo.write("docs/nist-800-53-alignment.md", "[flat](decisions/0001-flat.md) and [other](host-vars.md)\n")
        drift.check_nist_alignment_currency()
        assert drift.errors == []


class TestDocPathMention:
    @pytest.fixture(autouse=True)
    def _real_docs(self, repo):
        repo.write("docs/decisions/0001-x/revision-000.md", "# real\n")
        repo.write("docs/decisions/README.md", "# Index\n")
        repo.write("docs/projects/real-project.md", "# real\n")

    def test_existing_paths_pass_in_every_scanned_file_type(self, repo):
        real = "docs/decisions/0001-x/revision-000.md"
        repo.write("tools/tool.py", f"# see {real}\n")
        repo.write("ansible/roles/r/tasks/main.yaml", f"# see {real}\n")
        repo.write("tools/run.sh", f"# see {real}\n")
        repo.write("pyproject.toml", f"# see {real}\n")
        repo.write("docs/topic.md", f"See `{real}` and docs/decisions/README.md#anything.\n")
        drift.check_doc_path_mentions()
        assert drift.errors == []

    def test_a_missing_path_fails_in_comments_and_docs(self, repo):
        repo.write("tools/tool.py", "# see docs/decisions/0009-gone/revision-000.md.\n")
        repo.write("docs/topic.md", "See docs/decisions/0008-gone/revision-001.md for more.\n")
        drift.check_doc_path_mentions()
        assert len(drift.errors) == 2, drift.errors
        assert any("tool.py" in e and "0009-gone/revision-000.md" in e for e in drift.errors)
        assert any("topic.md" in e and "0008-gone/revision-001.md" in e for e in drift.errors)

    @pytest.mark.parametrize("name", ["a.py", "a.yaml", "a.yml", "a.sh", "a.toml", "a.hcl", "a.j2", "a.md"])
    def test_a_missing_path_is_caught_in_every_scanned_extension(self, repo, name):
        missing = "docs/decisions/0009-gone/revision-000.md"
        repo.write(f"scan/{name}", f"# see {missing}\n")
        drift.check_doc_path_mentions()
        assert len(drift.errors) == 1, drift.errors

    def test_unscanned_extensions_are_ignored(self, repo):
        repo.write("notes.txt", "docs/decisions/0009-gone/revision-000.md\n")
        drift.check_doc_path_mentions()
        assert drift.errors == []

    def test_project_doc_paths_are_checked_too(self, repo):
        repo.write("tools/tool.py", "# see docs/projects/real-project.md\n")
        repo.write("ansible/inventory.yaml", "# see docs/projects/real-project.md#stages\n")
        drift.check_doc_path_mentions()
        assert drift.errors == []
        repo.write("tools/other.py", "# see docs/projects/finished-and-deleted.md\n")
        drift.check_doc_path_mentions()
        assert len(drift.errors) == 1, drift.errors
        assert "finished-and-deleted.md" in drift.errors[0]

    def test_a_deleted_project_is_referred_to_by_name_not_path(self, repo):
        repo.write("tools/tool.py", "# moved from the finished openbao-python-client-hardening project\n")
        drift.check_doc_path_mentions()
        assert drift.errors == []

    def test_old_flat_style_path_fails_after_a_refile(self, repo):
        repo.write("tools/tool.py", "# docs/decisions/0001-old-flat-name.md\n")
        drift.check_doc_path_mentions()
        assert len(drift.errors) == 1, drift.errors

    def test_placeholders_and_names_without_a_path_are_ignored(self, repo):
        repo.write("docs/topic.md", "Pattern docs/decisions/NNNN-slug/revision-NNN.md; the draft `deleted-draft` was removed.\n")
        drift.check_doc_path_mentions()
        assert drift.errors == []

    def test_test_fixtures_are_exempt(self, repo):
        repo.write("tools/tests/doc_scripts/fixture.py", 'x = "docs/decisions/0099-fake/revision-000.md"\n')
        drift.check_doc_path_mentions()
        assert drift.errors == []
