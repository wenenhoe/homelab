"""Unit tests for doc_frontmatter.py - the schema of record for decision
and project docs. Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _doc_fixtures import project, revision, write_doc
from doc_scripts import doc_frontmatter as fm_mod


class TestDocKind:
    @pytest.mark.parametrize(
        ("rel", "kind"),
        [
            pytest.param("docs/decisions/0013-secret-storage/revision-002.md", "adr-revision", id="decision-revision"),
            pytest.param("docs/projects/cd-agent.md", "project", id="project"),
        ],
    )
    def test_kind_is_decided_by_location(self, rel, kind):
        assert fm_mod.doc_kind(Path("/repo") / rel) == kind

    @pytest.mark.parametrize("rel", ["docs/decisions/0013-secret-storage.md", "docs/decisions/drafts/some-draft.md"])
    def test_flat_files_and_drafts_are_rejected(self, rel):
        with pytest.raises(SystemExit, match="lineage directories"):
            fm_mod.doc_kind(Path("/repo") / rel)

    def test_outside_decisions_and_projects_is_rejected(self):
        with pytest.raises(SystemExit):
            fm_mod.doc_kind(Path("/repo/docs/ansible.md"))


class TestReadFrontmatter:
    def test_flat_adr_files_no_longer_validate(self, root):
        path = write_doc(root, "docs/decisions/0001-x.md", {"id": "ADR-0001", "title": "t", "type": "adr", "status": "accepted"})
        with pytest.raises(SystemExit, match="lineage directories"):
            fm_mod.read_frontmatter(path)

    def test_type_must_match_location(self, root):
        path = write_doc(root, "docs/projects/p.md", {"id": "PROJ-p", "title": "t", "type": "adr", "status": "done", "summary": "s"})
        with pytest.raises(SystemExit, match="doesn't match its location"):
            fm_mod.read_frontmatter(path)

    def test_missing_frontmatter_and_required_fields(self, root):
        path = root / "docs/projects/p.md"
        path.parent.mkdir(parents=True)
        path.write_text("# no frontmatter\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="missing frontmatter"):
            fm_mod.read_frontmatter(path)
        no_title = write_doc(root, "docs/projects/q.md", {"id": "PROJ-q", "type": "project", "status": "done"})
        with pytest.raises(SystemExit, match="missing required field 'title'"):
            fm_mod.read_frontmatter(no_title)


def _lettered_file_without_a_candidate_field(root: Path) -> Path:
    path = revision(root, "0047-x", 0, letter="a")
    path.write_text(path.read_text(encoding="utf-8").replace("candidate: a\n", ""), encoding="utf-8")
    return path


class TestRevisionValidation:
    @pytest.mark.parametrize("status", sorted(fm_mod.ADR_REVISION_STATUS))
    def test_every_revision_status_is_accepted(self, root, status):
        extra = {"superseded_by": 2} if status == "superseded" else {}
        path = revision(root, "0013-secret-storage", 1, status=status, **extra)
        assert fm_mod.read_frontmatter(path)["status"] == status

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"id": "ADR-0099"}, id="id doesn't match directory"),
            pytest.param({"revision": 7}, id="revision doesn't match filename"),
            pytest.param({"revision": "1"}, id="revision is a string"),
            pytest.param({"topic": "misc"}, id="unknown topic"),
            pytest.param({"solution": "  "}, id="empty solution"),
            pytest.param({"status": "superseded"}, id="superseded without superseded_by"),
            pytest.param({"status": "accepted", "superseded_by": 1}, id="superseded_by on a non-superseded revision"),
            pytest.param({"supersedes": 0}, id="supersedes itself"),
            pytest.param({"supersedes": True}, id="supersedes is a bool"),
            pytest.param({"narrows": ["ADR-0015"]}, id="narrows is a list"),
            pytest.param({"related": ["0014"]}, id="related isn't ADR ids"),
            pytest.param({"former_ids": "ADR-0027"}, id="former_ids isn't a list"),
        ],
    )
    def test_rejected_frontmatter(self, root, overrides):
        path = revision(root, "0013-secret-storage", 0, **overrides)
        with pytest.raises(SystemExit):
            fm_mod.read_frontmatter(path)

    @pytest.mark.parametrize("topic", list(fm_mod.TOPICS))
    def test_every_topic_is_accepted_including_security_hardening(self, root, topic):
        path = revision(root, "0001-x", 0, topic=topic)
        assert fm_mod.read_frontmatter(path)["topic"] == topic

    def test_security_hardening_has_its_display_name(self):
        assert fm_mod.TOPICS["security-hardening"] == "Security & hardening"

    def test_a_competing_candidate_file_and_its_frontmatter_agree(self, root):
        ok = revision(root, "0044-x", 0, letter="a")
        assert fm_mod.read_frontmatter(ok)["candidate"] == "a"
        assert ok.name == "revision-000-a.md"

    @pytest.mark.parametrize(
        "build",
        [
            pytest.param(lambda root: revision(root, "0045-x", 0, letter="a", candidate="b"), id="lettered file, wrong candidate"),
            pytest.param(_lettered_file_without_a_candidate_field, id="lettered file, no candidate field"),
            pytest.param(lambda root: revision(root, "0046-x", 0, candidate="a"), id="unlettered file with a candidate field"),
        ],
    )
    def test_a_competing_candidate_file_and_its_frontmatter_must_agree(self, root, build):
        with pytest.raises(SystemExit):
            fm_mod.read_frontmatter(build(root))

    def test_references_may_name_a_lettered_candidate(self, root):
        path = revision(root, "0044-x", 1, status="accepted", supersedes="0-b")
        assert fm_mod.read_frontmatter(path)["supersedes"] == "0-b"

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"supersedes": "1-a"}, id="same generation"),
            pytest.param({"supersedes": "b"}, id="malformed"),
            pytest.param({"supersedes": "0-B"}, id="uppercase letter"),
            pytest.param({"supersedes": "0"}, id="a quoted bare number"),
            pytest.param({"supersedes": -1}, id="negative"),
        ],
    )
    def test_malformed_references_to_a_candidate_are_rejected(self, root, overrides):
        with pytest.raises(SystemExit):
            fm_mod.read_frontmatter(revision(root, "0100-y", 1, **overrides))

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            pytest.param(0, "0", id="int-0"),
            pytest.param(3, "3", id="int-3"),
            pytest.param("0-b", "0-b", id="str-0-b"),
            pytest.param("12-z", "12-z", id="str-12-z"),
            pytest.param("0", None, id="str-0"),
            pytest.param("b", None, id="str-b"),
            pytest.param("0-B", None, id="str-0-B"),
            pytest.param("01-a", None, id="str-01-a"),
            pytest.param(-1, None, id="int-minus-1"),
            pytest.param(True, None, id="bool-true"),
            pytest.param(None, None, id="none"),
            pytest.param(1.5, None, id="float"),
        ],
    )
    def test_ref_label(self, value, expected):
        assert fm_mod.ref_label(value) == expected

    def test_lineage_loads_candidates_in_generation_then_letter_order(self, root):
        revision(root, "0044-x", 1, status="working")
        revision(root, "0044-x", 0, letter="b", status="abandoned")
        revision(root, "0044-x", 0, letter="a", status="accepted")
        (lineage,) = fm_mod.load_lineages(root)
        assert [r.label for r in lineage.revisions] == ["0-a", "0-b", "1"]
        assert [r.number for r in lineage.revisions] == [0, 0, 1]
        assert lineage.get("0-b").status == "abandoned"
        assert lineage.get(0) is None, "a generation with lettered candidates is not addressable by its bare number"
        assert lineage.get(1).label == "1"
        assert lineage.current().label == "0-a"
        assert [r.label for r in lineage.pending_successors()] == ["1"]

    def test_the_original_is_revision_zero(self, root):
        path = revision(root, "0013-secret-storage", 0)
        assert fm_mod.read_frontmatter(path)["revision"] == 0
        assert path.name == "revision-000.md"
        with pytest.raises(SystemExit):
            fm_mod.read_frontmatter(revision(root, "0014-x", 0, revision=1))

    def test_relations_accepted(self, root):
        path = revision(root, "0013-secret-storage", 1, status="accepted", supersedes=0, narrows="ADR-0015", related=["ADR-0014"], former_ids=["ADR-0027"])
        assert fm_mod.read_frontmatter(path)["narrows"] == "ADR-0015"


class TestProjectValidation:
    @pytest.mark.parametrize("status", sorted(fm_mod.PROJECT_LIFECYCLE_STATUS))
    def test_every_lifecycle_status_is_accepted(self, root, status):
        assert fm_mod.read_frontmatter(project(root, f"p-{status}", status=status))["status"] == status

    @pytest.mark.parametrize("status", ["in-progress", "blocked"])
    def test_the_pre_lifecycle_statuses_are_rejected(self, root, status):
        with pytest.raises(SystemExit, match="isn't valid"):
            fm_mod.read_frontmatter(project(root, "p", status=status, blocked_reason="x"))

    def test_summary_is_required(self, root):
        path = write_doc(root, "docs/projects/p.md", {"id": "PROJ-p", "title": "p", "type": "project", "status": "done"})
        with pytest.raises(SystemExit, match="summary"):
            fm_mod.read_frontmatter(path)

    def test_blocked_rules(self, root):
        assert fm_mod.read_frontmatter(project(root, "a", status="building", blocked=True, blocked_reason="waiting on hardware"))["blocked"] is True
        assert fm_mod.read_frontmatter(project(root, "ok", status="building", blocked=False))["blocked"] is False

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"status": "building", "blocked": True}, id="blocked true without reason"),
            pytest.param({"status": "building", "blocked": "yes"}, id="blocked isn't a bool"),
        ],
    )
    def test_malformed_blocked_fields_are_rejected(self, root, overrides):
        with pytest.raises(SystemExit):
            fm_mod.read_frontmatter(project(root, "b", **overrides))

    def test_depends_on_shape(self, root):
        ok = project(root, "ok", depends_on=[{"project": "PROJ-other", "reason": "consumes its bootstrap"}])
        assert len(fm_mod.read_frontmatter(ok)["depends_on"]) == 1

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param([{"project": "PROJ-other"}], id="no reason"),
            pytest.param([{"project": "PROJ-other", "reason": " "}], id="blank reason"),
            pytest.param([{"project": "other", "reason": "x"}], id="bad id"),
            pytest.param({"project": "PROJ-other", "reason": "x"}, id="not a list"),
        ],
    )
    def test_malformed_depends_on_is_rejected(self, root, value):
        with pytest.raises(SystemExit):
            fm_mod.read_frontmatter(project(root, "b", depends_on=value))

    def test_track_and_phase_need_their_parent_label(self, root):
        ok = project(root, "ok", super_project="cd", track="security", phase="bootstrap")
        assert fm_mod.read_frontmatter(ok)["phase"] == "bootstrap"

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"track": "security"}, id="track without super_project"),
            pytest.param({"super_project": "cd", "phase": "bootstrap"}, id="phase without track"),
            pytest.param({"super_project": "cd", "track": "Security Track"}, id="track isn't a slug"),
            pytest.param({"super_project": "cd", "track": "t", "phase": 1}, id="phase isn't a slug"),
        ],
    )
    def test_a_track_or_phase_without_its_parent_label_is_rejected(self, root, overrides):
        with pytest.raises(SystemExit):
            fm_mod.read_frontmatter(project(root, "b", **overrides))

    def test_allowed_paths_shape(self, root):
        ok = project(root, "ok", allowed_paths=["src/**", "tools/doc_scripts/doc_*.py", "README.md"])
        assert len(fm_mod.read_frontmatter(ok)["allowed_paths"]) == 3

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param("src/**", id="not a list"),
            pytest.param([], id="empty list"),
            pytest.param(["src/**", 3], id="non-string entry"),
            pytest.param(["src/**", " "], id="blank entry"),
            pytest.param(["/etc/passwd"], id="absolute"),
            pytest.param(["src/../secrets/**"], id="parent traversal"),
            *[pytest.param([p], id=f"blanket {p!r}") for p in sorted(fm_mod.BLANKET_PATHS)],
        ],
    )
    def test_malformed_allowed_paths_are_rejected(self, root, value):
        with pytest.raises(SystemExit):
            fm_mod.read_frontmatter(project(root, "b", allowed_paths=value))

    def test_decision_and_super_project_shape(self, root):
        assert fm_mod.read_frontmatter(project(root, "a", decision="ADR-0013/1", super_project="pull-based-cd"))["decision"] == "ADR-0013/1"

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"decision": "ADR-0013"}, id="decision without a revision"),
            pytest.param({"decision": ["ADR-0013/1"]}, id="decision is a list"),
            pytest.param({"super_project": "Pull Based"}, id="super_project isn't a slug"),
        ],
    )
    def test_malformed_decision_and_super_project_are_rejected(self, root, overrides):
        with pytest.raises(SystemExit):
            fm_mod.read_frontmatter(project(root, "b", **overrides))


class TestLineageLoading:
    def test_load_and_current_revision(self, root):
        revision(root, "0013-secret-storage", 0, status="superseded", superseded_by=1)
        revision(root, "0013-secret-storage", 1, status="accepted", supersedes=0)
        revision(root, "0013-secret-storage", 2, status="working")
        (lineage,) = fm_mod.load_lineages(root)
        assert lineage.id == "ADR-0013"
        assert lineage.current().number == 1
        assert [r.number for r in lineage.pending_successors()] == [2]

    def test_current_falls_back_to_newest_pending_then_newest(self, root):
        revision(root, "0001-a", 0, status="working")
        revision(root, "0001-a", 1, status="approved")
        revision(root, "0002-b", 0, status="abandoned")
        by_id = {lineage.id: lineage for lineage in fm_mod.load_lineages(root)}
        assert by_id["ADR-0001"].current().number == 1
        assert by_id["ADR-0001"].pending_successors() == []
        assert by_id["ADR-0002"].current().number == 0

    def test_retired_counts_as_the_live_revision(self, root):
        revision(root, "0001-a", 0, status="retired")
        (lineage,) = fm_mod.load_lineages(root)
        assert lineage.current().status == "retired"

    def test_stray_files_and_empty_directories_are_rejected(self, root):
        revision(root, "0001-a", 0)
        (root / "docs/decisions/0001-a/README.md").write_text("# manifest\n", encoding="utf-8")
        with pytest.raises(SystemExit, match=r"only revision-NNN.md"):
            fm_mod.load_lineages(root)
        (root / "docs/decisions/0001-a/README.md").unlink()
        (root / "docs/decisions/0002-empty").mkdir()
        with pytest.raises(SystemExit, match="no revision files"):
            fm_mod.load_lineages(root)

    def test_flat_files_are_not_lineages(self, root):
        write_doc(root, "docs/decisions/0001-flat.md", {"id": "ADR-0001", "title": "t", "type": "adr", "status": "accepted"})
        assert fm_mod.load_lineages(root) == []
        assert fm_mod.load_lineages(root / "nowhere") == []
