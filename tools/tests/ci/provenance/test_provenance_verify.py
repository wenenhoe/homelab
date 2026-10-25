"""Tests for ci.provenance.verify.

`gh` and `docker` (which runs `cosign`) run through doubles bound to ci.proc.run's signature, since the
real ones need a registry and GitHub. The doubles that stand for a verifier
exit 0 only for the repository, identity or issuer the real tool would accept,
so an entry that names the wrong one must fail. Nothing here reaches a real
publisher; a run against the real ones is not covered by these tests.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import create_autospec

import pytest
from ci import proc
from ci.provenance import registry, verify
from ci.provenance.pins import Pin
from ci.provenance.registry import Attested, Signed, Unsigned

D1 = "sha256:" + "1" * 64
D2 = "sha256:" + "2" * 64
D3 = "sha256:" + "3" * 64
SOURCE = "docker/tool/compose.yaml"
ISSUER = "https://token.actions.githubusercontent.com"
IDENTITY = "https://github.com/owner/tool/.github/workflows/release.yml@refs/tags/v1.0.0"
PATTERN = r"^https://github\.com/owner/tool/\.github/workflows/release\.yml@refs/tags/v[0-9]+\.[0-9]+\.[0-9]+$"
KEY = f"{registry.KEYS}/tool.pub"
DOCKER_RUN = ["docker", "run", "--rm", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--env", "TUF_ROOT=/tmp"]
COSIGN = [*DOCKER_RUN, verify.COSIGN_IMAGE, "verify"]


def pin(digest: str = D1, repository: str = "owner/tool", registry_host: str = "ghcr.io") -> Pin:
    return Pin(registry_host, repository, digest, (SOURCE,))


def completed(returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout="")


def tool(returncode: int = 0):
    return create_autospec(proc.run, return_value=completed(returncode))


def option(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


def gh_that_attests_only(repository: str):
    """Exits 0 only for the repository that built the image, as `gh attestation verify --repo` does."""

    def run(args: list[str], cwd: Path, capture: bool = False) -> subprocess.CompletedProcess[str]:
        return completed(0 if option(args, "--repo") == repository else 1)

    return create_autospec(proc.run, side_effect=run)


def gh_that_attests_a_build_from(repository: str, source_ref: str):
    """Exits 0 only for the repository and the ref the build ran from, as `gh attestation verify --repo --source-ref` does."""

    def run(args: list[str], cwd: Path, capture: bool = False) -> subprocess.CompletedProcess[str]:
        asked = option(args, "--source-ref") if "--source-ref" in args else source_ref
        return completed(0 if option(args, "--repo") == repository and asked == source_ref else 1)

    return create_autospec(proc.run, side_effect=run)


def cosign_that_accepts(identity: str, issuer: str):
    """Exits 0 only for the identity and issuer the image was signed with, as `cosign verify` does."""

    def run(args: list[str], cwd: Path, capture: bool = False) -> subprocess.CompletedProcess[str]:
        return completed(0 if option(args, "--certificate-identity") == identity and option(args, "--certificate-oidc-issuer") == issuer else 1)

    return create_autospec(proc.run, side_effect=run)


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def check(root, sleeps):
    def run_entry(entry, pins, run) -> verify.Outcome:
        return verify.check_entry(root, entry, pins, run, sleeps.append)

    return run_entry


def attested(repository: str = "owner/tool", image: str = "ghcr.io/owner/tool", source_ref: str | None = None) -> Attested:
    return Attested(image=image, repository=repository, source_ref=source_ref)


class TestAttested:
    def test_a_digest_that_passes_gh_passes_and_gh_is_asked_for_the_entrys_repository(self, root, check):
        run = tool()
        assert check(attested(), [pin()], run).errors == []
        run.assert_called_once_with(["gh", "attestation", "verify", f"oci://ghcr.io/owner/tool@{D1}", "--repo", "owner/tool"], root, True)

    def test_an_entry_that_fixes_a_ref_has_gh_enforce_it(self, root, check):
        run = tool()
        assert check(attested(source_ref="refs/heads/main"), [pin()], run).errors == []
        run.assert_called_once_with(
            ["gh", "attestation", "verify", f"oci://ghcr.io/owner/tool@{D1}", "--repo", "owner/tool", "--source-ref", "refs/heads/main"], root, True
        )

    def test_an_image_built_from_another_ref_fails_when_the_entry_fixes_main_and_passes_when_it_fixes_nothing(self, check):
        from_develop = gh_that_attests_a_build_from("owner/tool", "refs/heads/develop")
        failed = check(attested(source_ref="refs/heads/main"), [pin()], from_develop)
        assert failed.errors == [f"ghcr.io/owner/tool@{D1} ({SOURCE}): gh attestation verify exited 1 after 3 attempts"]
        assert check(attested(), [pin()], from_develop).errors == []
        assert check(attested(source_ref="refs/heads/main"), [pin()], gh_that_attests_a_build_from("owner/tool", "refs/heads/main")).errors == []

    def test_a_failing_exit_fails_the_digest_after_every_attempt(self, check, sleeps):
        run = tool(returncode=1)
        outcome = check(attested(), [pin()], run)
        assert outcome.errors == [f"ghcr.io/owner/tool@{D1} ({SOURCE}): gh attestation verify exited 1 after 3 attempts"]
        assert (run.call_count, sleeps) == (3, [2.0, 4.0])

    def test_a_call_that_fails_once_and_then_passes_passes(self, check, sleeps):
        run = create_autospec(proc.run, side_effect=[completed(1), completed(0)])
        assert check(attested(), [pin()], run).errors == []
        assert (run.call_count, sleeps) == (2, [2.0])

    def test_an_image_attested_for_another_repository_fails_and_the_right_one_passes(self, check):
        run = gh_that_attests_only("owner/tool")
        assert check(attested("owner/tool"), [pin()], run).errors == []
        wrong = check(attested("someone/else"), [pin()], run)
        assert wrong.errors == [f"ghcr.io/owner/tool@{D1} ({SOURCE}): gh attestation verify exited 1 after 3 attempts"]

    def test_a_missing_gh_fails_the_digest_without_a_retry(self, check, sleeps):
        run = create_autospec(proc.run, side_effect=FileNotFoundError("gh"))
        assert check(attested(), [pin()], run).errors == [f"ghcr.io/owner/tool@{D1} ({SOURCE}): gh is not installed"]
        assert (run.call_count, sleeps) == (1, [])

    def test_every_digest_pinned_for_the_repository_is_verified_and_no_other_repositorys_is(self, check):
        run = tool()
        outcome = check(attested(), [pin(D1), pin(D2), pin(D3, repository="someone/else")], run)
        assert (outcome.errors, outcome.checked) == ([], 2)
        assert [call.args[0][3] for call in run.call_args_list] == [f"oci://ghcr.io/owner/tool@{D1}", f"oci://ghcr.io/owner/tool@{D2}"]

    def test_a_digest_that_fails_among_digests_that_pass_fails_the_entry_and_names_that_digest(self, check):
        def run(args: list[str], cwd: Path, capture: bool = False) -> subprocess.CompletedProcess[str]:
            return completed(1 if D2 in args[3] else 0)

        outcome = check(attested(), [pin(D1), pin(D2)], create_autospec(proc.run, side_effect=run))
        assert outcome.errors == [f"ghcr.io/owner/tool@{D2} ({SOURCE}): gh attestation verify exited 1 after 3 attempts"]

    def test_a_docker_hub_image_is_named_by_the_host_its_images_go_by(self, check):
        run = tool()
        check(attested(image="ubuntu"), [pin(repository="library/ubuntu", registry_host="registry-1.docker.io")], run)
        assert run.call_args.args[0][3] == f"oci://docker.io/library/ubuntu@{D1}"


def signed(**fields) -> Signed:
    return Signed(image="ghcr.io/owner/tool", **fields)


class TestSignedWithAnIdentity:
    def test_an_identity_written_out_is_passed_to_cosign_with_its_issuer(self, root, check):
        run = tool()
        assert check(signed(identity=IDENTITY, issuer=ISSUER), [pin()], run).errors == []
        run.assert_called_once_with([*COSIGN, "--certificate-identity", IDENTITY, "--certificate-oidc-issuer", ISSUER, f"ghcr.io/owner/tool@{D1}"], root, True)

    def test_a_pattern_is_passed_to_cosign_as_a_pattern(self, root, check):
        run = tool()
        assert check(signed(identity_regexp=PATTERN, issuer=ISSUER), [pin()], run).errors == []
        run.assert_called_once_with(
            [*COSIGN, "--certificate-identity-regexp", PATTERN, "--certificate-oidc-issuer", ISSUER, f"ghcr.io/owner/tool@{D1}"], root, True
        )

    def test_cosign_runs_from_the_pinned_image_with_no_capability_and_no_file_of_the_tree(self, check):
        run = tool()
        check(signed(identity=IDENTITY, issuer=ISSUER), [pin()], run)
        argv = run.call_args.args[0]
        assert argv[: len(DOCKER_RUN)] == DOCKER_RUN
        assert verify.COSIGN_IMAGE in argv
        assert "--volume" not in argv

    def test_an_image_signed_by_an_identity_other_than_the_entrys_fails_and_the_right_one_passes(self, check):
        run = cosign_that_accepts(IDENTITY, ISSUER)
        assert check(signed(identity=IDENTITY, issuer=ISSUER), [pin()], run).errors == []
        other = check(signed(identity="https://github.com/attacker/tool/.github/workflows/release.yml@refs/heads/main", issuer=ISSUER), [pin()], run)
        assert other.errors == [f"ghcr.io/owner/tool@{D1} ({SOURCE}): cosign verify exited 1 after 3 attempts"]

    def test_an_image_signed_under_an_issuer_other_than_the_entrys_fails(self, check):
        run = cosign_that_accepts(IDENTITY, ISSUER)
        other = check(signed(identity=IDENTITY, issuer="https://accounts.example.invalid"), [pin()], run)
        assert other.errors == [f"ghcr.io/owner/tool@{D1} ({SOURCE}): cosign verify exited 1 after 3 attempts"]

    def test_a_failing_exit_fails_the_digest_after_every_attempt(self, check, sleeps):
        run = tool(returncode=1)
        assert check(signed(identity=IDENTITY, issuer=ISSUER), [pin()], run).errors == [
            f"ghcr.io/owner/tool@{D1} ({SOURCE}): cosign verify exited 1 after 3 attempts"
        ]
        assert (run.call_count, sleeps) == (3, [2.0, 4.0])

    def test_a_missing_docker_fails_the_digest_without_a_retry(self, check):
        run = create_autospec(proc.run, side_effect=FileNotFoundError("docker"))
        assert check(signed(identity=IDENTITY, issuer=ISSUER), [pin()], run).errors == [f"ghcr.io/owner/tool@{D1} ({SOURCE}): docker is not installed"]
        assert run.call_count == 1

    def test_every_pinned_digest_is_verified_at_its_own_digest(self, check):
        run = tool()
        check(signed(identity=IDENTITY, issuer=ISSUER), [pin(D1), pin(D2)], run)
        assert [call.args[0][-1] for call in run.call_args_list] == [f"ghcr.io/owner/tool@{D1}", f"ghcr.io/owner/tool@{D2}"]


class TestSignedWithAKey:
    def commit_key(self, root: Path) -> Path:
        path = root / KEY
        path.parent.mkdir(parents=True)
        path.write_text("-----BEGIN PUBLIC KEY-----\n-----END PUBLIC KEY-----\n")
        return path

    def test_the_committed_key_is_the_only_file_the_container_can_read_and_no_identity_is_passed(self, root, check):
        path = self.commit_key(root)
        run = tool()
        assert check(signed(key=KEY), [pin()], run).errors == []
        run.assert_called_once_with(
            [*DOCKER_RUN, "--volume", f"{path}:/key.pub:ro", verify.COSIGN_IMAGE, "verify", "--key", "/key.pub", f"ghcr.io/owner/tool@{D1}"], root, True
        )

    def test_a_failing_exit_fails_the_digest(self, root, check):
        self.commit_key(root)
        outcome = check(signed(key=KEY), [pin()], tool(returncode=1))
        assert outcome.errors == [f"ghcr.io/owner/tool@{D1} ({SOURCE}): cosign verify exited 1 after 3 attempts"]

    def test_a_key_that_is_not_committed_fails_the_entry_once_and_cosign_is_never_run(self, check):
        run = tool()
        outcome = check(signed(key=KEY), [pin(D1), pin(D2)], run)
        assert outcome.errors == ["the key file tool.pub is not committed"]
        run.assert_not_called()


class TestUnsignedAndUnpinned:
    def test_an_unsigned_image_passes_without_either_tool_being_run(self, check):
        run = tool(returncode=1)
        outcome = check(Unsigned(image="ghcr.io/owner/tool", reason="the publisher signs nothing"), [pin(D1), pin(D2)], run)
        assert (outcome.errors, outcome.checked) == ([], 2)
        run.assert_not_called()

    @pytest.mark.parametrize(
        "entry",
        [
            pytest.param(attested(), id="attested"),
            pytest.param(signed(identity=IDENTITY, issuer=ISSUER), id="signed"),
            pytest.param(signed(key=KEY), id="signed-with-a-key"),
        ],
    )
    def test_an_entry_whose_repository_has_no_pinned_digest_has_nothing_to_verify(self, check, entry):
        run = tool(returncode=1)
        outcome = check(entry, [pin(repository="someone/else")], run)
        assert (outcome.errors, outcome.checked) == ([], 0)
        run.assert_not_called()


class TestReport:
    def test_every_pass_exits_zero_and_the_summary_names_each_images_tier(self):
        outcomes = [verify.Outcome(attested(), 1, []), verify.Outcome(Unsigned(image="ubuntu", reason="r"), 1, [])]
        assert verify.report(outcomes, []) == (["2 images: 2 passed, 0 failed (ghcr.io/owner/tool [attested], ubuntu [unsigned])"], 0)

    def test_a_failure_is_an_error_annotation_and_fails_the_run(self):
        lines, code = verify.report([verify.Outcome(attested(), 1, ["x@sha256:1 (a): gh attestation verify exited 1 after 3 attempts"])], [])
        assert lines == [
            "::error::ghcr.io/owner/tool: x@sha256:1 (a): gh attestation verify exited 1 after 3 attempts",
            "1 images: 0 passed, 1 failed (ghcr.io/owner/tool [attested] FAILED)",
        ]
        assert code == 1

    def test_one_failure_among_passes_still_fails_the_run(self):
        outcomes = [verify.Outcome(Unsigned(image="ubuntu", reason="r"), 1, []), verify.Outcome(attested(), 1, ["boom"])]
        assert verify.report(outcomes, [])[1] == 1

    def test_a_reference_that_could_not_be_verified_fails_the_run_though_every_entry_passes(self):
        lines, code = verify.report([verify.Outcome(attested(), 1, [])], ["ghcr.io/Owner/bad:1@sha256:1 (a): not a sha256 digest reference a registry accepts"])
        assert lines[0] == "::error::ghcr.io/Owner/bad:1@sha256:1 (a): not a sha256 digest reference a registry accepts"
        assert code == 1

    def test_an_entry_with_no_pinned_digest_is_a_notice_and_does_not_fail_the_run(self):
        lines, code = verify.report([verify.Outcome(attested(), 0, [])], [])
        assert lines[0] == "::notice::ghcr.io/owner/tool: no digest of it is pinned in the tree, so there is nothing to verify"
        assert code == 0


def tree(root: Path, *refs: str, renovate: str = "{}\n") -> Path:
    """A repository with one compose file naming each reference, and the Renovate config the collector reads."""
    (root / ".github").mkdir(exist_ok=True)
    (root / ".github/renovate.json5").write_text(renovate)
    (root / "docker/tool").mkdir(parents=True, exist_ok=True)
    (root / SOURCE).write_text("services:\n" + "".join(f"  s{n}:\n    image: {ref}\n" for n, ref in enumerate(refs)))
    return root


class TestMain:
    def run_main(self, root: Path, entries, *names: str, run=None, sleeps: list[float] | None = None) -> int:
        return verify.main(list(names), root=root, entries=tuple(entries), run=run or tool(), sleep=(sleeps if sleeps is not None else []).append)

    def test_a_run_where_every_digest_checks_out_exits_zero(self, root, capsys):
        code = self.run_main(tree(root, f"ghcr.io/owner/tool:1.0@{D1}"), [attested()])
        assert (code, capsys.readouterr().out.strip()) == (0, "1 images: 1 passed, 0 failed (ghcr.io/owner/tool [attested])")

    def test_a_digest_that_does_not_check_out_exits_non_zero_and_says_which_and_where(self, root, capsys):
        code = self.run_main(tree(root, f"ghcr.io/owner/tool:1.0@{D1}"), [attested()], run=tool(returncode=1))
        assert code == 1
        assert f"::error::ghcr.io/owner/tool: ghcr.io/owner/tool@{D1} ({SOURCE}): gh attestation verify exited 1 after 3 attempts" in capsys.readouterr().out

    def test_a_digest_refreshed_to_an_image_nobody_attested_fails_for_that_digest_only(self, root, capsys):
        def run(args: list[str], cwd: Path, capture: bool = False) -> subprocess.CompletedProcess[str]:
            return completed(1 if args[3].endswith(D2) else 0)

        code = self.run_main(
            tree(root, f"ghcr.io/owner/tool:1.0@{D1}", f"ghcr.io/owner/tool:1.1@{D2}"), [attested()], run=create_autospec(proc.run, side_effect=run)
        )
        out = capsys.readouterr().out
        assert (code, f"ghcr.io/owner/tool@{D2}" in out, f"ghcr.io/owner/tool@{D1} (" in out) == (1, True, False)

    def test_every_entry_is_checked_even_after_one_fails(self, root, capsys):
        entries = [attested(), Unsigned(image="ghcr.io/owner/other", reason="the publisher signs nothing")]
        code = self.run_main(tree(root, f"ghcr.io/owner/tool:1@{D1}", f"ghcr.io/owner/other:1@{D2}"), entries, run=tool(returncode=1))
        assert (code, "2 images: 1 passed, 1 failed (ghcr.io/owner/tool [attested] FAILED, ghcr.io/owner/other [unsigned])" in capsys.readouterr().out) == (
            1,
            True,
        )

    def test_named_images_are_the_only_ones_checked(self, root, capsys):
        run = tool()
        entries = [attested(), attested("owner/other", image="ghcr.io/owner/other")]
        code = self.run_main(tree(root, f"ghcr.io/owner/tool:1@{D1}", f"ghcr.io/owner/other:1@{D2}"), entries, "ghcr.io/owner/other", run=run)
        assert (code, capsys.readouterr().out.strip(), run.call_count) == (0, "1 images: 1 passed, 0 failed (ghcr.io/owner/other [attested])", 1)

    def test_an_image_that_is_not_in_the_registry_is_a_usage_error(self, root, capsys):
        with pytest.raises(SystemExit) as stopped:
            self.run_main(tree(root), [attested()], "nothing")
        assert stopped.value.code == 2
        assert "no registry entry named nothing" in capsys.readouterr().err

    def test_a_registry_that_names_one_repository_twice_is_a_usage_error_and_nothing_is_run(self, root, capsys):
        run = tool()
        with pytest.raises(SystemExit) as stopped:
            self.run_main(tree(root, f"ghcr.io/owner/tool:1@{D1}"), [attested(), Unsigned(image="ghcr.io/owner/tool", reason="r")], run=run)
        assert stopped.value.code == 2
        assert "name the same image repository" in capsys.readouterr().err
        run.assert_not_called()

    def test_a_reference_that_cannot_be_handed_to_a_tool_fails_the_run_and_no_tool_sees_it(self, root, capsys):
        run = tool()
        code = self.run_main(tree(root, "ghcr.io/Owner/tool:1@sha256:" + "1" * 64), [attested()], run=run)
        assert code == 1
        assert f"::error::ghcr.io/Owner/tool:1@sha256:{'1' * 64} ({SOURCE}): not a sha256 digest reference a registry accepts" in capsys.readouterr().out
        run.assert_not_called()

    def test_a_pin_the_collector_lost_fails_the_run(self, root, capsys):
        manager = {
            "customType": "regex",
            "datasourceTemplate": "docker",
            "description": "a pin",
            "managerFilePatterns": [r"/^nowhere\.txt$/"],
            "matchStrings": ["x"],
        }
        code = self.run_main(tree(root, f"ghcr.io/owner/tool:1@{D1}", renovate=json.dumps({"customManagers": [manager]})), [attested()])
        assert code == 1
        assert "::error::Renovate manager matches no file, so its pin moved or was removed: a pin" in capsys.readouterr().out

    def test_a_renovate_config_that_cannot_be_read_fails_the_run(self, root, capsys):
        code = self.run_main(root, [attested()])
        assert code == 1
        assert "::error::can't read .github/renovate.json5" in capsys.readouterr().err

    def test_the_run_is_written_to_the_step_summary_when_running_in_actions(self, root, monkeypatch):
        summary = root / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
        self.run_main(tree(root, f"ghcr.io/owner/tool:1@{D1}"), [attested()])
        assert summary.read_text() == "### Image provenance\n\n- 1 images: 1 passed, 0 failed (ghcr.io/owner/tool [attested])\n"
