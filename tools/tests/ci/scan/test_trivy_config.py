"""Tests for ci.scan.trivy_config.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ci.scan import trivy_config as tc


class Scratch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()

    def touch(self, rel: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\n")


class PlaybooksTests(Scratch):
    def test_yaml_files_first_then_yml_each_sorted_and_relative_to_ansible(self):
        for name in ("b.yaml", "a.yaml", "z.yml", "c.yml"):
            self.touch(f"ansible/playbooks/{name}")
        self.assertEqual(tc.playbooks(self.root), ["playbooks/a.yaml", "playbooks/b.yaml", "playbooks/c.yml", "playbooks/z.yml"])

    def test_other_files_directories_and_nested_playbooks_are_ignored(self):
        self.touch("ansible/playbooks/a.yaml")
        self.touch("ansible/playbooks/notes.md")
        self.touch("ansible/playbooks/sub/nested.yaml")
        (self.root / "ansible/playbooks/dir.yaml").mkdir()
        self.assertEqual(tc.playbooks(self.root), ["playbooks/a.yaml"])

    def test_no_playbooks_is_an_error(self):
        (self.root / "ansible/playbooks").mkdir(parents=True)
        with self.assertRaisesRegex(tc.NoPlaybooksError, "would cover nothing"):
            tc.playbooks(self.root)

    def test_a_missing_directory_is_an_error_not_an_empty_list(self):
        with self.assertRaises(tc.NoPlaybooksError):
            tc.playbooks(self.root)


class RenderTests(unittest.TestCase):
    def test_exact_output(self):
        self.assertEqual(
            tc.render(["playbooks/a.yaml", "playbooks/b.yml"]),
            'misconfiguration:\n  scanners:\n    - ansible\nansible:\n  playbooks:\n    - "playbooks/a.yaml"\n    - "playbooks/b.yml"\n',
        )

    def test_the_output_is_valid_yaml_with_the_structure_trivy_reads(self):
        config = yaml.safe_load(tc.render(["playbooks/a.yaml", 'playbooks/we"ird\\name.yaml']))
        self.assertEqual(config["misconfiguration"], {"scanners": ["ansible"]})
        self.assertEqual(config["ansible"]["playbooks"], ["playbooks/a.yaml", 'playbooks/we"ird\\name.yaml'])


class CliTests(Scratch):
    def run_main(self, output: Path) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with patch.object(tc, "REPO_ROOT", self.root), redirect_stdout(out), redirect_stderr(err):
            code = tc.main([str(output)])
        return code, out.getvalue(), err.getvalue()

    def test_writes_the_file_and_prints_it_for_the_job_log(self):
        self.touch("ansible/playbooks/a.yaml")
        target = self.root / "out.yaml"
        code, out, _ = self.run_main(target)
        self.assertEqual(code, 0)
        self.assertEqual(target.read_text(), out)
        self.assertIn('- "playbooks/a.yaml"', out)

    def test_no_playbooks_fails_without_writing(self):
        target = self.root / "out.yaml"
        code, _, err = self.run_main(target)
        self.assertEqual(code, 1)
        self.assertIn("::error::", err)
        self.assertFalse(target.exists())


class RealTreeTests(unittest.TestCase):
    def test_the_real_playbooks_are_all_listed(self):
        listed = tc.playbooks(tc.REPO_ROOT)
        on_disk = sorted(p.name for p in (tc.REPO_ROOT / "ansible/playbooks").iterdir() if p.is_file() and p.suffix in (".yaml", ".yml"))
        self.assertEqual(sorted(Path(p).name for p in listed), on_disk)

    def test_every_listed_playbook_exists_relative_to_ansible(self):
        for path in tc.playbooks(tc.REPO_ROOT):
            with self.subTest(path=path):
                self.assertTrue((tc.REPO_ROOT / "ansible" / path).is_file())


if __name__ == "__main__":
    unittest.main()
