"""Tests for ci.gates.deploy_ordering.

The verdict logic runs against sample logs; the playbook runs go through a
stub runner, so nothing here needs ansible. The log samples are minimal
strings carrying the signatures the check looks for, not captured output.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import io
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ci.gates import deploy_ordering as do

REPO_ROOT = do.REPO_ROOT
GOOD_LOG = (
    "TASK [restore : Fail if archive missing]\nfatal: [ci-managed-host]: FAILED! => {msg: /nonexistent/x.tar.gz not found on the controller. Did you mean...}\n"
)


def completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class ClassifyRestoreTests(unittest.TestCase):
    def test_failing_with_the_archive_message_passes(self):
        verdict = do.classify_restore(2, GOOD_LOG)
        self.assertTrue(verdict.ok)
        self.assertTrue(verdict.message.startswith("OK:"))

    def test_remote_addr_in_the_log_is_the_regression(self):
        verdict = do.classify_restore(2, "UNREACHABLE! => {remote_addr: None}\n" + GOOD_LOG)
        self.assertFalse(verdict.ok)
        self.assertIn("ordering regression", verdict.message)

    def test_secrets_generated_undefined_on_one_line_is_the_regression(self):
        verdict = do.classify_restore(2, "error: 'secrets_generated' is undefined\n")
        self.assertFalse(verdict.ok)
        self.assertIn("ordering regression", verdict.message)

    def test_secrets_generated_and_undefined_on_different_lines_is_not_the_signature(self):
        # grep -E matched per line, and so does this: the two words must share one.
        verdict = do.classify_restore(2, "secrets_generated\nis undefined\n")
        self.assertFalse(verdict.ok)
        self.assertIn("not with the expected", verdict.message)

    def test_regression_signature_wins_over_the_expected_message(self):
        self.assertIn("ordering regression", do.classify_restore(2, GOOD_LOG + "remote_addr\n").message)

    def test_success_is_an_error_even_with_the_message_in_the_log(self):
        verdict = do.classify_restore(0, GOOD_LOG)
        self.assertFalse(verdict.ok)
        self.assertIn("succeeded instead", verdict.message)

    def test_failure_without_the_archive_message_is_an_error(self):
        verdict = do.classify_restore(2, "fatal: something else broke\n")
        self.assertFalse(verdict.ok)
        self.assertIn("not with the expected", verdict.message)

    def test_regression_signature_is_checked_before_the_exit_code(self):
        self.assertIn("ordering regression", do.classify_restore(0, "remote_addr\n").message)


class RunTests(unittest.TestCase):
    def stub(self, result: subprocess.CompletedProcess[str]):
        calls: list[tuple[list[str], Path, bool]] = []

        def run(args: list[str], cwd: Path, capture: bool) -> subprocess.CompletedProcess[str]:
            calls.append((args, cwd, capture))
            return result

        return run, calls

    def run_main(self, mode: str, result: subprocess.CompletedProcess[str]):
        run, calls = self.stub(result)
        out = io.StringIO()
        with redirect_stdout(out):
            code = do.main([mode], run)
        return code, out.getvalue(), calls

    def test_restore_runs_both_playbooks_as_one_invocation_from_the_ansible_dir(self):
        _, _, calls = self.run_main("restore", completed(2, GOOD_LOG))
        ((args, cwd, capture),) = calls
        self.assertEqual(cwd, do.ANSIBLE_DIR)
        self.assertTrue(capture)
        self.assertEqual(args[0], "ansible-playbook")
        self.assertEqual(args[args.index("playbooks/bootstrap-secrets.yaml") + 1], "playbooks/restore.yaml")
        self.assertEqual(args[args.index("--limit") + 1], "ci-managed-host,localhost")
        self.assertIn("restore_archive_local_path=/nonexistent/ci-ordering-check-archive.tar.gz", args)
        self.assertIn('restore_volumes=["ci_ordering_check_data"]', args)
        self.assertIn("@/tmp/ci-secrets-registry-no-vault.json", args)

    def test_restore_passes_on_the_expected_failure_and_prints_the_log(self):
        code, out, _ = self.run_main("restore", completed(2, GOOD_LOG))
        self.assertEqual(code, 0)
        self.assertIn("not found on the controller", out)
        self.assertIn("OK:", out)

    def test_restore_fails_with_an_error_annotation(self):
        code, out, _ = self.run_main("restore", completed(0, "all good\n"))
        self.assertEqual(code, 1)
        self.assertIn("::error::Expected a failure", out)

    def test_deploy_runs_the_real_playbook_with_a_tag_that_matches_nothing(self):
        code, _, calls = self.run_main("deploy", completed(0))
        ((args, cwd, capture),) = calls
        self.assertEqual(code, 0)
        self.assertEqual(cwd, do.ANSIBLE_DIR)
        self.assertFalse(capture)
        self.assertEqual(args[args.index("playbooks/deploy.yaml") + 1 :][:2], ["--tags", "ci-deploy-ordering-check-tag-matches-nothing"])
        self.assertEqual(args[args.index("--limit") + 1], "ci-managed-host,localhost")
        self.assertIn("compose_deploy_dir=/tmp/compose-deploy-ordering-check", args)

    def test_deploy_returns_the_playbooks_exit_code(self):
        self.assertEqual(self.run_main("deploy", completed(4))[0], 4)

    def test_the_real_runner_merges_stderr_into_stdout_in_order(self):
        script = "import sys; print('a'); sys.stdout.flush(); print('b', file=sys.stderr); sys.stderr.flush(); print('c')"
        result = do._run([sys.executable, "-c", script], REPO_ROOT, True)
        self.assertEqual(result.stdout.split(), ["a", "b", "c"])


class RepoInvariantTests(unittest.TestCase):
    def test_referenced_inventory_and_playbooks_exist(self):
        self.assertTrue((do.ANSIBLE_DIR / do.INVENTORY).is_file())
        for playbook in ("deploy", "bootstrap-secrets", "restore"):
            with self.subTest(playbook=playbook):
                self.assertTrue((do.ANSIBLE_DIR / f"playbooks/{playbook}.yaml").is_file())

    def test_the_expected_failure_message_is_still_the_restore_roles_own(self):
        text = (REPO_ROOT / "ansible/roles/restore/tasks/main.yaml").read_text()
        # The role wraps the message across lines, so compare with whitespace collapsed.
        self.assertIn(do.EXPECTED_FAILURE, " ".join(text.split()))


if __name__ == "__main__":
    unittest.main()
