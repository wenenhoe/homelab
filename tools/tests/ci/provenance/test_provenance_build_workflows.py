"""The four build workflows attest the digest they push, with no wider token than that needs.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from ci.images.registry import IMAGES, REGISTRY

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOWS = REPO_ROOT / ".github/workflows"
JOB_PERMISSIONS = {"attestations": "write", "contents": "read", "id-token": "write", "packages": "write"}
BY_COMMIT = re.compile(r"^actions/attest@[0-9a-f]{40}$")


def _workflow(key):
    return yaml.safe_load((WORKFLOWS / f"build-{key}-image.yml").read_text())


def _job(key):
    (job,) = _workflow(key)["jobs"].values()
    return job


def _steps(job, name):
    return [index for index, step in enumerate(job["steps"]) if step.get("name") == name]


KEYS = list(IMAGES)


@pytest.mark.parametrize("key", KEYS)
class TestBuildWorkflowAttests:
    def test_the_build_job_holds_only_the_permissions_attesting_needs(self, key):
        assert _job(key)["permissions"] == JOB_PERMISSIONS

    def test_the_workflow_as_a_whole_stays_read_only(self, key):
        assert _workflow(key)["permissions"] == {"contents": "read"}

    def test_the_attest_action_is_pinned_to_a_commit(self, key):
        (index,) = _steps(_job(key), "Attest the pushed digest")
        assert BY_COMMIT.match(_job(key)["steps"][index]["uses"].split(" ")[0])

    def test_it_attests_the_digest_the_build_step_pushed(self, key):
        job = _job(key)
        (build,) = _steps(job, "Build and push")
        (attest,) = _steps(job, "Attest the pushed digest")
        assert build < attest
        assert job["steps"][attest]["with"]["subject-digest"] == f"${{{{ steps.{job['steps'][build]['id']}.outputs.digest }}}}"

    def test_it_names_the_image_the_registry_publishes(self, key):
        (index,) = _steps(_job(key), "Attest the pushed digest")
        assert _job(key)["steps"][index]["with"]["subject-name"] == f"{REGISTRY}/{IMAGES[key].name}"

    def test_the_statement_is_pushed_beside_the_image_without_a_storage_record(self, key):
        (index,) = _steps(_job(key), "Attest the pushed digest")
        options = _job(key)["steps"][index]["with"]
        assert (options["push-to-registry"], options["create-storage-record"]) == (True, False)
