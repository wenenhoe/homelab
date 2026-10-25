"""Tests for ci.verification.

`gh` and `cosign` run through doubles bound to ci.proc.run's signature, since
the real ones need GitHub or a registry.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import create_autospec

import pytest
from ci import proc, verification


def completed(returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout="")


@pytest.fixture
def sleeps() -> list[float]:
    return []


class TestBackoff:
    def test_the_first_attempt_does_not_wait_and_each_later_one_waits_twice_as_long(self):
        assert [verification.backoff(attempt) for attempt in range(4)] == [1.0, 2.0, 4.0, 8.0]


class TestVerified:
    def test_a_tool_that_exits_zero_passes_after_one_call_and_no_wait(self, root, sleeps):
        run = create_autospec(proc.run, return_value=completed(0))
        assert verification.verified("tool check", ["tool", "check"], root, run, sleeps.append) is None
        run.assert_called_once_with(["tool", "check"], root, True)
        assert sleeps == []

    def test_a_tool_that_keeps_failing_fails_after_every_attempt_with_its_last_exit_code(self, root, sleeps):
        run = create_autospec(proc.run, side_effect=[completed(1), completed(1), completed(2)])
        assert verification.verified("tool check", ["tool"], root, run, sleeps.append) == "tool check exited 2 after 3 attempts"
        assert (run.call_count, sleeps) == (3, [2.0, 4.0])

    def test_a_tool_that_fails_and_then_passes_passes(self, root, sleeps):
        run = create_autospec(proc.run, side_effect=[completed(1), completed(0)])
        assert verification.verified("tool check", ["tool"], root, run, sleeps.append) is None
        assert (run.call_count, sleeps) == (2, [2.0])

    def test_the_attempts_it_is_given_are_the_ones_it_makes(self, root, sleeps):
        run = create_autospec(proc.run, return_value=completed(1))
        assert verification.verified("tool check", ["tool"], root, run, sleeps.append, attempts=2) == "tool check exited 1 after 2 attempts"
        assert (run.call_count, sleeps) == (2, [2.0])

    def test_a_tool_that_is_not_installed_fails_at_once_naming_it(self, root, sleeps):
        run = create_autospec(proc.run, side_effect=FileNotFoundError("tool"))
        assert verification.verified("tool check", ["tool", "check"], root, run, sleeps.append) == "tool is not installed"
        assert (run.call_count, sleeps) == (1, [])


class TestAttestation:
    def test_gh_is_asked_for_the_subject_and_the_repository_in_the_directory_given(self, root):
        run = create_autospec(proc.run, return_value=completed(0))
        assert verification.attestation("oci://ghcr.io/owner/tool@sha256:abc", "owner/tool", root, run) is None
        run.assert_called_once_with(["gh", "attestation", "verify", "oci://ghcr.io/owner/tool@sha256:abc", "--repo", "owner/tool"], root, True)

    def test_gh_is_asked_for_the_source_ref_when_one_is_given(self, root):
        run = create_autospec(proc.run, return_value=completed(0))
        assert verification.attestation("oci://ghcr.io/owner/tool@sha256:abc", "owner/tool", root, run, source_ref="refs/heads/main") is None
        run.assert_called_once_with(
            ["gh", "attestation", "verify", "oci://ghcr.io/owner/tool@sha256:abc", "--repo", "owner/tool", "--source-ref", "refs/heads/main"], root, True
        )

    def test_a_subject_gh_does_not_accept_fails_after_every_attempt(self, root, sleeps):
        def run(args: list[str], cwd: Path, capture: bool = False) -> subprocess.CompletedProcess[str]:
            return completed(0 if args[args.index("--repo") + 1] == "owner/tool" else 1)

        double = create_autospec(proc.run, side_effect=run)
        assert verification.attestation("file.tar.gz", "owner/tool", root, double, sleeps.append) is None
        assert verification.attestation("file.tar.gz", "someone/else", root, double, sleeps.append) == "gh attestation verify exited 1 after 3 attempts"
