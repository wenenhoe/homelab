"""Tests for review_criteria.criteria: one case per criterion, the diff reader, then the documented table.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from review_criteria import __main__ as cli
from review_criteria import criteria as c

REPO_ROOT = Path(__file__).resolve().parents[3]
CODE = ("x = 1",)


def change(path: str, added: tuple[str, ...] = CODE, removed: tuple[str, ...] = ()) -> c.Change:
    return c.Change(path, added, removed)


def ids(*changes: c.Change) -> list[str]:
    return [hit.criterion.id for hit in c.assess(list(changes)).hits]


def test_a_change_that_touches_nothing_of_note_trips_nothing():
    assessment = c.assess([change("docker/bentopdf/notes.txt"), change("ansible/roles/dashy/tasks/main.yaml")])
    assert assessment.hits == ()
    assert not assessment.recommend


class TestWhatCounts:
    def test_blank_and_comment_lines_do_not_count(self):
        assert ids(change(".github/workflows/x.yml", added=("", "   ", "# note", "  // note"))) == []

    def test_a_real_line_counts_whether_added_or_removed(self):
        assert ids(change(".github/workflows/x.yml", added=(), removed=("on: push",))) == ["R1"]

    def test_a_markdown_file_never_counts(self):
        assert ids(change("docker/openbao/README.md", added=("text",)), change(".github/NOTES.md", added=("text",))) == []

    def test_a_change_to_documents_alone_never_recommends(self):
        assert not c.assess([change(f"docs/topics/a{n}.md", added=("x",) * 900) for n in range(40)]).recommend


class TestMajor:
    @pytest.mark.parametrize(
        ("criterion", "path"),
        [
            ("R1", ".github/workflows/pr-checks.yml"),
            ("R1", ".githooks/pre-applypatch"),
            ("R1", "pyproject.toml"),
            ("R1", "uv.lock"),
            ("R1", "tools/land_series/land.py"),
            ("R1", "tools/cd_agent/agent.py"),
            ("R1", "tools/openbao_utils/bootstrap.py"),
            ("R1", "tools/cloud_credentials/rotate.py"),
            ("R2", "ansible/roles/secrets/tasks/main.yaml"),
            ("R2", "ansible/roles/tinyauth_ca_trust/tasks/main.yaml"),
            ("R2", "docker/openbao/compose.yaml.j2"),
            ("R2", "docker/step-ca/compose.yaml.j2"),
            ("R2", "docker/tinyauth/compose.yaml"),
            ("R2", "ansible/inventory/group_vars/all/secret_catalog.yaml"),
            ("R3", "tools/ci/gates/app_catalog_rules.py"),
            ("R4", "tools/ci/gates/compose_hardening_rules.py"),
            ("R5", "ansible/roles/backup_agent/templates/compose.yaml.j2"),
            ("R5", "ansible/roles/restore/tasks/main.yaml"),
            ("R5", "ansible/roles/restore_discovery/tasks/main.yaml"),
            ("R5", "ansible/roles/cloud_sync/tasks/main.yaml"),
            ("R6", "tofu/main.tf"),
            ("R6", "tofu/terraform.tfvars"),
            ("R6", "tofu/modules/proxmox_ubuntu_vm/main.tf"),
        ],
    )
    def test_each_path_trips_its_criterion(self, criterion, path):
        assessment = c.assess([change(path)])
        assert criterion in [hit.criterion.id for hit in assessment.hits]
        assert assessment.recommend

    @pytest.mark.parametrize(
        "path",
        [
            "tools/tests/land_series/test_land_replay.py",
            "tools/doc_scripts/check_doc_change.py",
            "ansible/roles/secrets/molecule/default/converge.yml",
            "ansible/roles/backup_agent/molecule/default/verify.yml",
            "ansible/roles/caddy/tasks/main.yaml",
            "docker/dashy/compose.yaml",
            "tofu/scratch/ubuntu/main.tf",
            "tofu/modules/proxmox_ubuntu_vm/tests/vm.tftest.hcl",
            "tofu/README.md",
            "docs/topics/services/openbao.md",
        ],
    )
    def test_each_path_beside_them_trips_no_major_criterion(self, path):
        assert [i for i in ids(change(path)) if i.startswith("R")] == []

    def test_a_new_route_trips_r3_and_a_removed_one_does_not(self):
        catalog = "ansible/inventory/group_vars/all/app_catalog.yaml"
        assert ids(change(catalog, added=("        upstream: web:80",))) == ["R3"]
        assert ids(change(catalog, added=(), removed=("        upstream: web:80",))) == []

    @pytest.mark.parametrize("line", ["      - '0.0.0.0:80:80'", '      - "443:443/udp"', "      - 8080:80 # note", "      - '127.0.0.1:2222:22'"])
    def test_a_published_port_in_a_compose_file_trips_r3(self, line):
        assert ids(change("docker/web/compose.yaml", added=(line,))) == ["R3"]

    @pytest.mark.parametrize("line", ["      - ./data:/data", "      - data:/data", "    image: web:1", "    expose: ['80']"])
    def test_a_mount_or_other_line_is_not_a_published_port(self, line):
        assert ids(change("docker/web/compose.yaml", added=(line,))) == []

    def test_a_declared_backup_trips_r5_whether_added_or_removed(self):
        catalog = "ansible/inventory/group_vars/all/app_catalog.yaml"
        assert ids(change(catalog, added=("    backup:",))) == ["R5"]
        assert ids(change(catalog, added=(), removed=("    backup:",))) == ["R5"]
        assert ids(change(catalog, added=("  backup_defaults:",))) == ["R5"]

    def test_evidence_names_the_files(self):
        hit = c.assess([change("tofu/main.tf"), change("tofu/variables.tf")]).hits[0]
        assert hit.evidence == ("tofu/main.tf", "tofu/variables.tf")


class TestMinor:
    def test_code_with_no_test_trips_r1_alone_and_does_not_recommend(self):
        assessment = c.assess([change("tools/utils/thing.py")])
        assert [hit.criterion.id for hit in assessment.hits] == ["r1"]
        assert not assessment.recommend

    def test_code_with_a_test_does_not_trip_r1(self):
        assert ids(change("tools/utils/thing.py"), change("tools/tests/utils/test_thing.py")) == []

    def test_a_molecule_change_counts_as_a_test(self):
        assert ids(change("ansible/roles/dashy/templates/x.sh"), change("ansible/roles/dashy/molecule/default/verify.yml")) == []

    def test_a_file_that_is_not_code_does_not_trip_r1(self):
        assert ids(change("ansible/roles/dashy/tasks/main.yaml")) == []

    def test_size_by_lines_trips_r2(self):
        big = change("tools/tests/utils/test_big.py", added=("x = 1",) * c.MINOR_LINES)
        assert ids(big) == ["r2"]
        assert ids(change("tools/tests/utils/test_big.py", added=("x = 1",) * (c.MINOR_LINES - 1))) == []

    def test_size_by_files_trips_r2(self):
        files = [change(f"tools/tests/utils/test_{n}.py") for n in range(c.MINOR_FILES)]
        assert ids(*files) == ["r2"]
        assert ids(*files[:-1]) == []

    def test_documents_and_the_lock_file_are_not_counted_toward_size(self):
        assert ids(change("docs/topics/a.md", added=("x",) * 5000), change("uv.lock", added=("x",) * 5000)) == ["R1"]

    def test_both_minors_together_recommend(self):
        assessment = c.assess([change(f"tools/utils/m{n}.py", added=("x = 1",) * 30) for n in range(c.MINOR_FILES)])
        assert [hit.criterion.id for hit in assessment.hits] == ["r1", "r2"]
        assert assessment.recommend


class TestParseDiff:
    DIFF = """\
diff --git a/a.py b/a.py
index 1..2 100644
--- a/a.py
+++ b/a.py
@@ -1,2 +1,2 @@
-old
+new
+more
diff --git a/gone.py b/gone.py
deleted file mode 100644
--- a/gone.py
+++ /dev/null
@@ -1 +0,0 @@
-bye
diff --git a/fresh.py b/fresh.py
new file mode 100644
--- /dev/null
+++ b/fresh.py
@@ -0,0 +1 @@
+hi
diff --git a/img.png b/img.png
Binary files a/img.png and b/img.png differ
"""

    def test_each_file_gets_its_added_and_removed_lines(self):
        changes = {change.path: change for change in c.parse_diff(self.DIFF)}
        assert changes["a.py"] == c.Change("a.py", ("new", "more"), ("old",))
        assert changes["gone.py"] == c.Change("gone.py", (), ("bye",))
        assert changes["fresh.py"] == c.Change("fresh.py", ("hi",), ())

    def test_a_binary_file_has_no_lines_and_so_trips_nothing(self):
        assert "img.png" not in {change.path for change in c.parse_diff(self.DIFF)}


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "tofu").mkdir()
    (tmp_path / "tofu" / "main.tf").write_text("a = 1\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "base")
    (tmp_path / "tofu" / "main.tf").write_text("a = 2\n")
    (tmp_path / "notes.md").write_text("hello\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "change")
    return tmp_path


class TestAgainstGit:
    def test_read_changes_returns_the_files_between_two_commits(self, repo):
        changes = {change.path: change for change in c.read_changes(str(repo), "HEAD~1", "HEAD")}
        assert changes["tofu/main.tf"] == c.Change("tofu/main.tf", ("a = 2",), ("a = 1",))
        assert changes["notes.md"].added == ("hello",)

    def test_main_prints_the_criteria_that_tripped_and_the_advice(self, repo, capsys):
        assert cli.main(["HEAD~1", "HEAD", "--repo", str(repo)]) == 0
        out = capsys.readouterr().out
        assert out.startswith("R6: production OpenTofu")
        assert out.rstrip().endswith("Worth asking for a review.")

    def test_main_says_so_when_nothing_calls_for_one(self, repo, capsys):
        assert cli.main(["HEAD", "HEAD", "--repo", str(repo)]) == 0
        assert capsys.readouterr().out == "No criterion calls for a review.\n"


class TestDocumentedTable:
    def test_the_doc_lists_every_criterion_with_its_kind(self):
        doc = (REPO_ROOT / "docs/topics/security/policy/pr-review.md").read_text()
        rows = re.findall(r"^\| (R\d|r\d) \| (major|minor) \|", doc, re.MULTILINE)
        assert rows == [(criterion.id, criterion.kind) for criterion in c.CRITERIA]

    def test_the_thresholds_in_the_doc_match_the_code(self):
        doc = (REPO_ROOT / "docs/topics/security/policy/pr-review.md").read_text()
        assert f"{c.MINOR_LINES} or more changed lines, or {c.MINOR_FILES} or more files" in doc

    def test_criterion_ids_are_unique(self):
        assert len({criterion.id for criterion in c.CRITERIA}) == len(c.CRITERIA)
