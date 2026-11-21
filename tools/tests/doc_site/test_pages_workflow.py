"""How the documentation site is deployed and checked: the workflow that deploys it, the job that tries the same build on a pull
request, and the filter that queues it. Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
PAGES = REPO_ROOT / ".github/workflows/pages.yml"
PR_CHECKS = REPO_ROOT / ".github/workflows/pr-checks.yml"
FILTERS = REPO_ROOT / ".github/detect-changes-filters.yml"
DEPLOY_PERMISSIONS = {"pages": "write", "id-token": "write"}
BUILD = "python -m doc_site --commit"
PINNED = re.compile(r"^[\w.-]+/[\w.-]+(/[\w./-]+)?@[0-9a-f]{40}$")


def permission_errors(workflow: dict) -> list[str]:
    """What is wrong with the permissions of a deploy workflow: a `contents` write anywhere, or a deploy job that holds more than a deployment."""
    errors = []
    grants = {"workflow": workflow.get("permissions") or {}} | {name: job.get("permissions") or {} for name, job in workflow["jobs"].items()}
    errors += [f"{where} holds contents: write" for where, granted in grants.items() if isinstance(granted, dict) and granted.get("contents") == "write"]
    errors += [f"{where} grants write-all" for where, granted in grants.items() if granted == "write-all"]
    if workflow["jobs"]["deploy"].get("permissions") != DEPLOY_PERMISSIONS:
        errors.append(f"deploy must hold exactly {DEPLOY_PERMISSIONS}")
    errors += [f"{name} holds a write permission" for name, job in workflow["jobs"].items() if name != "deploy" and "write" in str(job.get("permissions", ""))]
    return errors


@pytest.fixture(scope="module")
def workflow():
    return yaml.safe_load(PAGES.read_text())


@pytest.fixture(scope="module")
def pr_checks():
    return yaml.safe_load(PR_CHECKS.read_text())


def step_index(job, needle: str) -> int:
    (found,) = [i for i, step in enumerate(job["steps"]) if needle in step.get("run", "") + step.get("uses", "")]
    return found


class TestTriggers:
    def test_it_runs_on_a_push_to_main_and_on_demand_and_nothing_else(self, workflow):
        triggers = workflow[True]  # YAML 1.1 reads the key `on` as a boolean
        assert triggers == {"push": {"branches": ["main"]}, "workflow_dispatch": {}}

    def test_one_run_goes_and_one_waits_and_none_is_cancelled(self, workflow):
        assert workflow["concurrency"] == {"group": "pages", "cancel-in-progress": False}


class TestPermissions:
    def test_the_workflow_as_written_passes(self, workflow):
        assert permission_errors(workflow) == []

    def test_the_workflow_reads_and_the_deploy_job_holds_a_deployment(self, workflow):
        assert workflow["permissions"] == {"contents": "read"}
        assert workflow["jobs"]["deploy"]["permissions"] == DEPLOY_PERMISSIONS

    def test_contents_write_on_the_deploy_job_fails(self, workflow):
        broken = copy.deepcopy(workflow)
        broken["jobs"]["deploy"]["permissions"]["contents"] = "write"
        assert permission_errors(broken)

    def test_contents_write_on_the_build_job_fails(self, workflow):
        broken = copy.deepcopy(workflow)
        broken["jobs"]["build"]["permissions"] = {"contents": "write"}
        assert permission_errors(broken)

    def test_contents_write_on_the_workflow_fails(self, workflow):
        broken = copy.deepcopy(workflow)
        broken["permissions"] = {"contents": "write"}
        assert permission_errors(broken)

    def test_write_all_fails(self, workflow):
        broken = copy.deepcopy(workflow)
        broken["jobs"]["deploy"]["permissions"] = "write-all"
        assert permission_errors(broken)

    def test_a_pages_write_on_the_build_job_fails(self, workflow):
        broken = copy.deepcopy(workflow)
        broken["jobs"]["build"]["permissions"] = {"contents": "read", "pages": "write"}
        assert permission_errors(broken)


class TestDeployJob:
    def test_it_runs_in_the_github_pages_environment(self, workflow):
        assert workflow["jobs"]["deploy"]["environment"]["name"] == "github-pages"

    def test_it_runs_no_repository_code(self, workflow):
        (step,) = workflow["jobs"]["deploy"]["steps"]
        assert step["uses"].startswith("actions/deploy-pages@")

    def test_it_waits_for_the_build(self, workflow):
        assert workflow["jobs"]["deploy"]["needs"] == "build"

    def test_the_runs_are_bounded(self, workflow):
        assert all(isinstance(job["timeout-minutes"], int) for job in workflow["jobs"].values())


class TestBuildJob:
    def test_the_layout_is_checked_after_the_build_and_before_the_upload(self, workflow):
        job = workflow["jobs"]["build"]
        assert step_index(job, BUILD) < step_index(job, "python -m doc_site.layout") < step_index(job, "upload-pages-artifact")

    def test_the_site_is_stamped_with_the_commit_it_is_built_from(self, workflow):
        job = workflow["jobs"]["build"]
        assert '--commit "$GITHUB_SHA"' in job["steps"][step_index(job, BUILD)]["run"]

    def test_the_checkout_leaves_no_credential_behind(self, workflow):
        (checkout,) = [step for step in workflow["jobs"]["build"]["steps"] if step.get("name") == "Checkout"]
        assert checkout["with"] == {"persist-credentials": False}

    def test_the_site_that_is_checked_is_the_site_that_is_uploaded(self, workflow):
        job = workflow["jobs"]["build"]
        built = job["steps"][step_index(job, BUILD)]["run"]
        checked = job["steps"][step_index(job, "python -m doc_site.layout")]["run"]
        uploaded = job["steps"][step_index(job, "upload-pages-artifact")]["with"]["path"]
        assert built.endswith('"$RUNNER_TEMP/site"') and checked.endswith('"$RUNNER_TEMP/site"')
        assert uploaded == "${{ runner.temp }}/site"


def test_every_external_action_is_pinned_by_commit(workflow):
    uses = [step["uses"] for job in workflow["jobs"].values() for step in job["steps"] if "uses" in step]
    assert [use for use in uses if not use.startswith("./") and not PINNED.match(use)] == []


class TestPullRequestJob:
    def test_it_runs_only_when_the_filter_matched(self, pr_checks):
        job = pr_checks["jobs"]["doc-site"]
        assert job["if"] == "needs.detect-changes.outputs.doc_site == 'true'"
        assert "detect-changes" in job["needs"]

    def test_detect_changes_passes_the_filters_verdict_on(self, pr_checks):
        assert pr_checks["jobs"]["detect-changes"]["outputs"]["doc_site"] == "${{ steps.filter.outputs.doc_site }}"

    def test_it_builds_and_checks_the_layout_as_the_deploy_does(self, pr_checks, workflow):
        pr, deploy = pr_checks["jobs"]["doc-site"], workflow["jobs"]["build"]
        commands = lambda job: [step["run"] for step in job["steps"] if "doc_site" in step.get("run", "")]  # noqa: E731
        assert commands(pr) == commands(deploy)

    def test_it_deploys_nothing_and_holds_no_write_permission(self, pr_checks):
        job = pr_checks["jobs"]["doc-site"]
        assert "permissions" not in job and "environment" not in job
        assert not any(step.get("uses", "").startswith("actions/deploy-pages") for step in job["steps"])

    def test_it_is_not_a_matrix_job_so_it_can_be_required_directly(self, pr_checks):
        assert "strategy" not in pr_checks["jobs"]["doc-site"]


@pytest.fixture(scope="module")
def paths():
    return yaml.safe_load(FILTERS.read_text())["doc_site"]


class TestFilter:
    @pytest.mark.parametrize(
        "path",
        [
            "tools/doc_site/layout.py",
            "tools/doc_scripts/generate_doc_indexes.py",
            "docs/decisions/0117-x/revision-000.md",
            "ansible/inventory/group_vars/all/app_catalog.yaml",
            ".github/workflows/pages.yml",
            "uv.lock",
        ],
    )
    def test_what_the_site_is_built_from_queues_the_job(self, paths, path):
        assert any(path == p or (p.endswith("/**") and path.startswith(p[:-2])) for p in paths)
