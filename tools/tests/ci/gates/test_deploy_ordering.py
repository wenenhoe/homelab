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
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from ci.gates import deploy_ordering as do

REPO_ROOT = do.REPO_ROOT
GOOD_LOG = (
    "TASK [restore : Fail if archive missing]\nfatal: [ci-managed-host]: FAILED! => {msg: /nonexistent/x.tar.gz not found on the controller. Did you mean...}\n"
)


def completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class TestClassifyRestore:
    def test_failing_with_the_archive_message_passes(self):
        verdict = do.classify_restore(2, GOOD_LOG)
        assert verdict.ok
        assert verdict.message.startswith("OK:")

    @pytest.mark.parametrize(
        ("exit_code", "log", "message"),
        [
            pytest.param(2, "UNREACHABLE! => {remote_addr: None}\n" + GOOD_LOG, "ordering regression", id="remote-addr-in-the-log"),
            pytest.param(2, "error: 'secrets_generated' is undefined\n", "ordering regression", id="secrets-generated-undefined-on-one-line"),
            # grep -E matched per line, and so does this: the two words must share one.
            pytest.param(2, "secrets_generated\nis undefined\n", "not with the expected", id="secrets-generated-and-undefined-on-different-lines"),
            pytest.param(0, GOOD_LOG, "succeeded instead", id="success-even-with-the-message-in-the-log"),
            pytest.param(2, "fatal: something else broke\n", "not with the expected", id="failure-without-the-archive-message"),
        ],
    )
    def test_a_restore_that_did_not_fail_as_expected_is_an_error(self, exit_code, log, message):
        verdict = do.classify_restore(exit_code, log)
        assert not verdict.ok
        assert message in verdict.message

    def test_regression_signature_wins_over_the_expected_message(self):
        assert "ordering regression" in do.classify_restore(2, GOOD_LOG + "remote_addr\n").message

    def test_regression_signature_is_checked_before_the_exit_code(self):
        assert "ordering regression" in do.classify_restore(0, "remote_addr\n").message


def stub(result: subprocess.CompletedProcess[str]):
    calls: list[tuple[list[str], Path, bool]] = []

    def run(args: list[str], cwd: Path, capture: bool) -> subprocess.CompletedProcess[str]:
        calls.append((args, cwd, capture))
        return result

    return run, calls


def run_main(mode: str, result: subprocess.CompletedProcess[str]):
    run, calls = stub(result)
    out = io.StringIO()
    with redirect_stdout(out):
        code = do.main([mode], run)
    return code, out.getvalue(), calls


class TestRun:
    def test_restore_runs_both_playbooks_as_one_invocation_from_the_ansible_dir(self):
        _, _, calls = run_main("restore", completed(2, GOOD_LOG))
        ((args, cwd, capture),) = calls
        assert cwd == do.ANSIBLE_DIR
        assert capture
        assert args[0] == "ansible-playbook"
        assert args[args.index("playbooks/bootstrap-secrets.yaml") + 1] == "playbooks/restore.yaml"
        assert args[args.index("--limit") + 1] == "ci-managed-host,localhost"
        assert "restore_archive_local_path=/nonexistent/ci-ordering-check-archive.tar.gz" in args
        assert 'restore_volumes=["ci_ordering_check_data"]' in args
        assert "@/tmp/ci-secret-catalog-no-vault.json" in args

    def test_restore_passes_on_the_expected_failure_and_prints_the_log(self):
        code, out, _ = run_main("restore", completed(2, GOOD_LOG))
        assert code == 0
        assert "not found on the controller" in out
        assert "OK:" in out

    def test_restore_fails_with_an_error_annotation(self):
        code, out, _ = run_main("restore", completed(0, "all good\n"))
        assert code == 1
        assert "::error::Expected a failure" in out

    def test_deploy_runs_the_real_playbook_with_a_tag_that_matches_nothing(self):
        code, _, calls = run_main("deploy", completed(0))
        ((args, cwd, capture),) = calls
        assert code == 0
        assert cwd == do.ANSIBLE_DIR
        assert not capture
        assert args[args.index("playbooks/deploy.yaml") + 1 :][:2] == ["--tags", "ci-deploy-ordering-check-tag-matches-nothing"]
        assert args[args.index("--limit") + 1] == "ci-managed-host,localhost"
        assert "compose_deploy_dir=/tmp/compose-deploy-ordering-check" in args

    def test_deploy_returns_the_playbooks_exit_code(self):
        assert run_main("deploy", completed(4))[0] == 4

    def test_the_real_runner_merges_stderr_into_stdout_in_order(self):
        script = "import sys; print('a'); sys.stdout.flush(); print('b', file=sys.stderr); sys.stderr.flush(); print('c')"
        result = do._run([sys.executable, "-c", script], REPO_ROOT, True)
        assert result.stdout.split() == ["a", "b", "c"]


class TestRepoInvariant:
    def test_the_referenced_inventory_exists(self):
        assert (do.ANSIBLE_DIR / do.INVENTORY).is_file()

    @pytest.mark.parametrize("playbook", ["deploy", "bootstrap-secrets", "restore"])
    def test_referenced_playbooks_exist(self, playbook):
        assert (do.ANSIBLE_DIR / f"playbooks/{playbook}.yaml").is_file()

    def test_the_expected_failure_message_is_still_the_restore_roles_own(self):
        text = (REPO_ROOT / "ansible/roles/restore/tasks/main.yaml").read_text()
        # The role wraps the message across lines, so compare with whitespace collapsed.
        assert do.EXPECTED_FAILURE in " ".join(text.split())
