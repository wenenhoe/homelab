"""Renovate runs against a `maintenance` that has been realigned with `main` (ADR 0076).

The realignment is the first thing the job does after checkout, and nothing lets
the run carry on when it fails: a Renovate run on a branch that is behind main
would open pull requests against code production no longer has.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml
from ci import json5

ROOT = Path(__file__).resolve().parents[4]
WORKFLOW = ROOT / ".github/workflows/renovate.yml"
CONFIG = ROOT / ".github/renovate.json5"


@pytest.fixture(scope="module")
def steps() -> list[dict]:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]["renovate"]["steps"]


def _index(steps: list[dict], needle: str) -> int:
    return next(i for i, step in enumerate(steps) if needle in (step.get("uses", "") + step.get("run", "")))


class TestRealignFirst:
    def test_it_runs_after_checkout_and_before_renovate(self, steps):
        assert _index(steps, "actions/checkout") < _index(steps, "ci.branches.realign") < _index(steps, "renovatebot/github-action")

    def test_the_checkout_has_full_history(self, steps):
        assert steps[_index(steps, "actions/checkout")]["with"]["fetch-depth"] == 0

    def test_a_failure_stops_the_run(self, steps, subtests):
        realign = steps[_index(steps, "ci.branches.realign")]
        renovate = steps[_index(steps, "renovatebot/github-action")]
        with subtests.test("the realignment is not allowed to fail quietly"):
            assert "continue-on-error" not in realign
            assert "if" not in realign
        with subtests.test("Renovate runs only after every earlier step succeeded"):
            assert "if" not in renovate

    def test_the_push_uses_the_app_token_not_the_default_one(self, steps, subtests):
        realign = steps[_index(steps, "ci.branches.realign")]
        with subtests.test("the token is the app's"):
            assert realign["env"]["APP_TOKEN"] == "${{ steps.app-token.outputs.token }}"
        with subtests.test("it is not put on the command line or written to config"):
            assert "git config" not in realign["run"]
            assert "--token" not in realign["run"]
        with subtests.test("the checkout does not keep a credential"):
            assert steps[_index(steps, "actions/checkout")]["with"]["persist-credentials"] is False


class TestAppToken:
    @pytest.fixture
    def mint(self, steps) -> dict:
        return steps[_index(steps, "actions/create-github-app-token")]

    def test_it_is_minted_before_it_is_used(self, steps):
        assert _index(steps, "actions/create-github-app-token") < _index(steps, "ci.branches.realign") < _index(steps, "renovatebot/github-action")

    def test_the_action_is_pinned_to_a_commit(self, mint):
        assert re.fullmatch(r"actions/create-github-app-token@[0-9a-f]{40}", mint["uses"])

    def test_it_names_the_app_by_its_client_id_and_key(self, mint, subtests):
        with subtests.test("client id"):
            assert mint["with"]["client-id"] == "${{ vars.RENOVATE_APP_CLIENT_ID }}"
        with subtests.test("key"):
            assert mint["with"]["private-key"] == "${{ secrets.RENOVATE_APP_PRIVATE_KEY }}"
        with subtests.test("the deprecated app id input is not used"):
            assert "app-id" not in mint["with"]

    def test_the_token_asks_for_no_more_than_the_documented_permissions(self, mint):
        asked = {key.removeprefix("permission-"): value for key, value in mint["with"].items() if key.startswith("permission-")}
        assert asked == {
            "contents": "write",
            "pull-requests": "write",
            "workflows": "write",
            "issues": "write",
            "statuses": "write",
            "vulnerability-alerts": "read",
        }

    def test_the_token_is_scoped_to_this_repository(self, mint, subtests):
        for key in ("owner", "repositories"):
            with subtests.test(key):
                assert key not in mint["with"]

    def test_renovate_and_its_host_rule_use_it(self, steps, subtests):
        renovate = steps[_index(steps, "renovatebot/github-action")]
        with subtests.test("platform token"):
            assert renovate["with"]["token"] == "${{ steps.app-token.outputs.token }}"
        with subtests.test("host rule"):
            assert "steps.app-token.outputs.token" in renovate["env"]["RENOVATE_HOST_RULES"]

    def test_no_personal_token_is_left(self):
        text = WORKFLOW.read_text()
        assert "RENOVATE_TOKEN" not in text
        assert "secrets.RENOVATE_TOKEN" not in text

    def test_the_global_author_equals_the_repository_one(self, steps, config):
        renovate = steps[_index(steps, "renovatebot/github-action")]
        assert renovate["env"]["RENOVATE_GIT_AUTHOR"] == config["gitAuthor"]

    def test_the_workflow_never_forces_a_push(self):
        assert not re.search(r"--force|--mirror|push\s+\S+\s+\+", WORKFLOW.read_text())


@pytest.fixture(scope="module")
def config() -> dict:
    return json5.loads(CONFIG.read_text())


class TestConfigTargetsMaintenance:
    def test_renovate_is_based_on_maintenance(self, config):
        assert config["baseBranchPatterns"] == ["maintenance"]

    def test_a_branch_is_rebased_only_when_maintenance_moved(self, config):
        assert config["rebaseWhen"] == "behind-base-branch"

    def test_control_the_parser_sees_real_keys(self, config):
        assert json.dumps(config["gitAuthor"]).startswith('"wenenhoe-renovate')


# What GitHub records for a commit Renovate makes through the API as the app.
BOT_EMAIL = "347765362+wenenhoe-renovate[bot]@users.noreply.github.com"
GITHUB_EMAIL = "noreply@github.com"
MAINTAINER_EMAIL = "33289235+wenenhoe@users.noreply.github.com"


def _git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True, env=env)
    return result.stdout.strip()


def _commit(repo: Path, name: str, author: str, committer: str) -> None:
    (repo / name).write_text(name)
    _git(repo, "add", name)
    env = {
        "PATH": "/usr/bin:/bin",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "a",
        "GIT_AUTHOR_EMAIL": author,
        "GIT_COMMITTER_NAME": "c",
        "GIT_COMMITTER_EMAIL": committer,
    }
    _git(repo, "commit", "--quiet", "-m", name, env=env)


def _is_edited(repo: Path, git_author_email: str) -> bool:
    """Renovate's `isBranchModified`: any author or committer in `base..branch` other than `gitAuthor` and GitHub's own."""
    emails = set(_git(repo, "log", "--format=%ae%n%ce", "maintenance..renovate/dep").split())
    return bool(emails - {git_author_email, GITHUB_EMAIL})


@pytest.fixture
def renovate_branch(tmp_path):
    """A Renovate branch of one API-made commit, cut from `maintenance`."""
    _git(tmp_path, "init", "--quiet", "--initial-branch=maintenance", ".")
    _commit(tmp_path, "base", MAINTAINER_EMAIL, MAINTAINER_EMAIL)
    _git(tmp_path, "checkout", "--quiet", "-b", "renovate/dep")
    _commit(tmp_path, "bump", BOT_EMAIL, GITHUB_EMAIL)
    _git(tmp_path, "checkout", "--quiet", "maintenance")
    return tmp_path


class TestOpenPullRequestsStayUpdatable:
    @pytest.fixture
    def configured_email(self, config) -> str:
        return re.search(r"<([^>]+)>", config["gitAuthor"]).group(1)

    def test_a_bot_commit_is_not_an_edit(self, renovate_branch, configured_email):
        assert not _is_edited(renovate_branch, configured_email)

    def test_maintenance_moving_on_does_not_make_it_an_edit(self, renovate_branch, configured_email, subtests):
        for step in ("main-1", "main-2", "main-3"):
            _commit(renovate_branch, step, MAINTAINER_EMAIL, GITHUB_EMAIL)
        with subtests.test("after a fast-forward over several commits"):
            assert not _is_edited(renovate_branch, configured_email)
        _git(renovate_branch, "checkout", "--quiet", "-b", "side", "maintenance~3")
        _commit(renovate_branch, "side", MAINTAINER_EMAIL, MAINTAINER_EMAIL)
        _git(renovate_branch, "checkout", "--quiet", "maintenance")
        _git(renovate_branch, "-c", f"user.email={MAINTAINER_EMAIL}", "-c", "user.name=m", "merge", "--quiet", "--no-ff", "-m", "merge", "side")
        with subtests.test("after a merge commit"):
            assert not _is_edited(renovate_branch, configured_email)

    def test_control_the_maintainer_as_author_reads_every_branch_as_edited(self, renovate_branch):
        assert _is_edited(renovate_branch, MAINTAINER_EMAIL)
