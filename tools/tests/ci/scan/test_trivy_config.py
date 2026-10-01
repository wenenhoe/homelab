"""Tests for ci.scan.trivy_config.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest
import yaml
from ci.scan import trivy_config as tc


def touch(root: Path, rel: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\n")


class TestPlaybooks:
    def test_yaml_files_first_then_yml_each_sorted_and_relative_to_ansible(self, root):
        for name in ("b.yaml", "a.yaml", "z.yml", "c.yml"):
            touch(root, f"ansible/playbooks/{name}")
        assert tc.playbooks(root) == ["playbooks/a.yaml", "playbooks/b.yaml", "playbooks/c.yml", "playbooks/z.yml"]

    def test_other_files_directories_and_nested_playbooks_are_ignored(self, root):
        touch(root, "ansible/playbooks/a.yaml")
        touch(root, "ansible/playbooks/notes.md")
        touch(root, "ansible/playbooks/sub/nested.yaml")
        (root / "ansible/playbooks/dir.yaml").mkdir()
        assert tc.playbooks(root) == ["playbooks/a.yaml"]

    def test_no_playbooks_is_an_error(self, root):
        (root / "ansible/playbooks").mkdir(parents=True)
        with pytest.raises(tc.NoPlaybooksError, match="would cover nothing"):
            tc.playbooks(root)

    def test_a_missing_directory_is_an_error_not_an_empty_list(self, root):
        with pytest.raises(tc.NoPlaybooksError):
            tc.playbooks(root)


class TestRender:
    def test_exact_output(self):
        assert (
            tc.render(["playbooks/a.yaml", "playbooks/b.yml"])
            == 'misconfiguration:\n  scanners:\n    - ansible\nansible:\n  playbooks:\n    - "playbooks/a.yaml"\n    - "playbooks/b.yml"\n'
        )

    def test_the_output_is_valid_yaml_with_the_structure_trivy_reads(self):
        config = yaml.safe_load(tc.render(["playbooks/a.yaml", 'playbooks/we"ird\\name.yaml']))
        assert config["misconfiguration"] == {"scanners": ["ansible"]}
        assert config["ansible"]["playbooks"] == ["playbooks/a.yaml", 'playbooks/we"ird\\name.yaml']


@pytest.fixture
def run_main(root, monkeypatch):
    def run(output: Path) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        monkeypatch.setattr(tc, "REPO_ROOT", root)
        with redirect_stdout(out), redirect_stderr(err):
            code = tc.main([str(output)])
        return code, out.getvalue(), err.getvalue()

    return run


class TestCli:
    def test_writes_the_file_and_prints_it_for_the_job_log(self, root, run_main):
        touch(root, "ansible/playbooks/a.yaml")
        target = root / "out.yaml"
        code, out, _ = run_main(target)
        assert code == 0
        assert target.read_text() == out
        assert '- "playbooks/a.yaml"' in out

    def test_no_playbooks_fails_without_writing(self, root, run_main):
        target = root / "out.yaml"
        code, _, err = run_main(target)
        assert code == 1
        assert "::error::" in err
        assert not target.exists()


class TestRealTree:
    def test_the_real_playbooks_are_all_listed(self):
        listed = tc.playbooks(tc.REPO_ROOT)
        on_disk = sorted(p.name for p in (tc.REPO_ROOT / "ansible/playbooks").iterdir() if p.is_file() and p.suffix in (".yaml", ".yml"))
        assert sorted(Path(p).name for p in listed) == on_disk

    def test_every_listed_playbook_exists_relative_to_ansible(self, subtests):
        for path in tc.playbooks(tc.REPO_ROOT):
            with subtests.test(path=path):
                assert (tc.REPO_ROOT / "ansible" / path).is_file()
