"""Tests for ci.gates.renovate_config: reading the pin out of the Renovate workflow, the
container command, and the verdict for each way the validator or Docker can answer. The
container run is replaced by a double bound to subprocess.run; the output below is what
renovate-config-validator 44.235.1 printed for a config whose rules named a manager
Renovate does not have. Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import create_autospec

import pytest
from ci.gates import renovate_config as rc

DIGEST = "sha256:" + "b" * 64
IMAGE = f"ghcr.io/renovatebot/renovate:44.235.1@{DIGEST}"
WORKFLOW = f"""jobs:
  renovate:
    steps:
      - uses: renovatebot/github-action@v46
        with:
          renovate-version: "44.235.1@{DIGEST}"
          token: x
"""
MESSAGE = (
    'Invalid packageRules[6].matchManagers: matchManagers had invalid values `[\\"uv\\"]` which are not part of the allowedValues, '
    "which are listed at https://docs.renovatebot.com/configuration-options/#packagerulesmatchmanagers"
)
REJECTED = f""" INFO: Validating .github/renovate.json5 as repo config
ERROR: Found errors in configuration
       "file": ".github/renovate.json5",
       "errors": [
         {{
           "topic": "Configuration Error",
           "message": "{MESSAGE}"
         }}
       ]
"""


def completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def docker(validator: subprocess.CompletedProcess[str] | None = None, pull_result: subprocess.CompletedProcess[str] | None = None):
    """Stands in for subprocess.run: `docker pull` and `docker run` each get their own answer."""

    def fake(args, **_kwargs):
        if args[:2] == ["docker", "pull"]:
            return pull_result or completed()
        return validator or completed()

    return create_autospec(subprocess.run, side_effect=fake)


@pytest.fixture
def tree(root: Path) -> Path:
    (root / ".github/workflows").mkdir(parents=True)
    (root / rc.WORKFLOW).write_text(WORKFLOW)
    (root / rc.CONFIG).write_text("{}\n")
    return root


class TestPinnedImage:
    def test_the_image_is_the_pinned_version_with_its_digest(self):
        assert rc.pinned_image(WORKFLOW) == IMAGE

    def test_a_pin_without_a_digest_is_the_tag_alone(self):
        assert rc.pinned_image(WORKFLOW.replace(f"@{DIGEST}", "")) == "ghcr.io/renovatebot/renovate:44.235.1"

    def test_the_real_workflow_names_a_pin(self):
        image = rc.pinned_image((rc.REPO_ROOT / rc.WORKFLOW).read_text())
        assert image.startswith("ghcr.io/renovatebot/renovate:")
        assert "@sha256:" in image

    @pytest.mark.parametrize(
        ("text", "match"),
        [
            pytest.param("jobs: {}\n", "found 0", id="no-pin"),
            pytest.param(WORKFLOW + WORKFLOW, "found 2", id="two-pins"),
            pytest.param(WORKFLOW.replace("44.235.1", "latest"), "not <major>", id="not-a-version"),
            pytest.param(WORKFLOW.replace(DIGEST, "sha256:abc"), "not <major>", id="short-digest"),
            pytest.param(WORKFLOW.replace(f'"44.235.1@{DIGEST}"', '""'), "not <major>", id="empty"),
        ],
    )
    def test_a_workflow_without_exactly_one_readable_pin_gives_no_verdict(self, text, match):
        with pytest.raises(rc.NoVerdict, match=match):
            rc.pinned_image(text)


class TestValidatorArgs:
    def test_it_runs_the_validator_strictly_on_a_repo_config_with_the_config_mounted_read_only(self):
        assert rc.validator_args(IMAGE, Path("/work/.github/renovate.json5")) == [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--mount",
            "type=bind,source=/work/.github/renovate.json5,target=/config/renovate.json5,readonly",
            IMAGE,
            "renovate-config-validator",
            "--strict",
            "--no-global",
            "/config/renovate.json5",
        ]


class TestCheck:
    def test_a_config_the_validator_accepts_gives_no_problem(self, tree):
        runner = docker(completed(0, " INFO: Config validated successfully against 1 file(s)\n"))
        assert rc.check(tree, runner) is None

    def test_the_image_is_pulled_before_it_is_run(self, tree):
        runner = docker()
        rc.check(tree, runner)
        assert [call.args[0][:2] for call in runner.call_args_list] == [["docker", "pull"], ["docker", "run"]]
        assert runner.call_args_list[0].args[0] == ["docker", "pull", "--quiet", IMAGE]
        assert runner.call_args_list[1].args[0] == rc.validator_args(IMAGE, (tree / rc.CONFIG).resolve())

    def test_a_config_the_validator_rejects_gives_everything_it_printed(self, tree):
        runner = docker(completed(1, "", REJECTED))
        assert rc.check(tree, runner) == REJECTED.strip()

    def test_output_on_both_streams_is_kept(self, tree):
        runner = docker(completed(1, "on stdout\n", "on stderr\n"))
        assert rc.check(tree, runner) == "on stdout\non stderr"

    def test_a_rejection_with_no_output_names_the_exit_status(self, tree):
        assert rc.check(tree, docker(completed(1))) == "exit status 1"

    def test_a_missing_config_gives_no_verdict(self, tree):
        (tree / rc.CONFIG).unlink()
        with pytest.raises(rc.NoVerdict, match="does not exist"):
            rc.check(tree, docker())

    def test_a_pull_that_fails_gives_no_verdict_with_the_last_line_of_the_error(self, tree):
        runner = docker(pull_result=completed(1, "", "Error response from daemon:\nunauthorized: denied\n"))
        with pytest.raises(rc.NoVerdict, match=r"cannot pull .*: unauthorized: denied"):
            rc.check(tree, runner)

    @pytest.mark.parametrize("status", [125, 126, 127])
    def test_docker_failing_to_run_the_image_gives_no_verdict_not_a_rejection(self, tree, status):
        runner = docker(completed(status, "", "Cannot connect to the Docker daemon"))
        with pytest.raises(rc.NoVerdict, match=rf"exit status {status}\): Cannot connect"):
            rc.check(tree, runner)

    def test_a_validator_that_runs_too_long_gives_no_verdict(self, tree):
        runner = create_autospec(subprocess.run, side_effect=[completed(), subprocess.TimeoutExpired("docker", rc.RUN_TIMEOUT)])
        with pytest.raises(rc.NoVerdict, match="did not finish"):
            rc.check(tree, runner)

    def test_a_missing_docker_gives_no_verdict(self, tree):
        runner = create_autospec(subprocess.run, side_effect=FileNotFoundError(2, "No such file or directory: 'docker'"))
        with pytest.raises(rc.NoVerdict, match="cannot pull"):
            rc.check(tree, runner)


class TestMain:
    def test_a_valid_config_exits_0(self, tree, capsys):
        assert rc.main(tree, docker()) == 0
        assert "is valid" in capsys.readouterr().out

    def test_a_rejected_config_exits_1_and_shows_the_validators_reason(self, tree, capsys):
        assert rc.main(tree, docker(completed(1, "", REJECTED))) == 1
        captured = capsys.readouterr()
        assert "matchManagers had invalid values" in captured.out
        assert "::error file=.github/renovate.json5::" in captured.err

    def test_no_verdict_exits_2_and_says_why(self, tree, capsys):
        assert rc.main(tree, docker(pull_result=completed(1, "", "unauthorized"))) == 2
        assert "cannot pull" in capsys.readouterr().err

    def test_an_unreadable_workflow_exits_2(self, tree, capsys):
        (tree / rc.WORKFLOW).unlink()
        assert rc.main(tree, docker()) == 2
        assert rc.WORKFLOW in capsys.readouterr().err
