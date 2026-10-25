"""Only main publishes an image (ADR 0076).

A job that pushes an image holds `packages: write`, so a run from `maintenance`
or `develop` could replace the image behind a tag the hosts pin. A workflow
finds the branch it runs on from its trigger, and a manual run takes any
branch, so each publishing job names `main` itself.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from ci.images.registry import IMAGES

WORKFLOWS = Path(__file__).resolve().parents[4] / ".github/workflows"
MAIN_ONLY = "github.ref == 'refs/heads/main'"
# The triggers a publishing workflow may have; none of them runs on a pull request or on someone else's push.
PUBLISH_TRIGGERS = {"push", "schedule", "workflow_dispatch"}


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _triggers(workflow: dict) -> dict:
    # PyYAML reads the bare key `on` as the boolean True.
    on = workflow.get("on", workflow.get(True))
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return dict.fromkeys(on)
    return on


def _pushes_an_image(job: dict) -> bool:
    if (job.get("permissions") or {}).get("packages") == "write":
        return True
    return any(
        str(step.get("uses", "")).startswith("docker/build-push-action@") and str((step.get("with") or {}).get("push", "false")).lower() != "false"
        for step in job.get("steps", [])
    )


def _publishing_jobs() -> list[tuple[Path, str, dict]]:
    return [(path, name, job) for path in sorted(WORKFLOWS.glob("*.yml")) for name, job in _load(path)["jobs"].items() if _pushes_an_image(job)]


PUBLISHING_JOBS = [pytest.param(path, name, job, id=f"{path.name}:{name}") for path, name, job in _publishing_jobs()]
PUBLISHING_WORKFLOWS = [pytest.param(path, id=path.name) for path in sorted({path for path, _, _ in _publishing_jobs()})]


def test_the_publishers_found_are_the_build_workflows_of_the_images_the_registry_lists():
    assert {path.name for path, _, _ in _publishing_jobs()} == {f"build-{key}-image.yml" for key in IMAGES}


@pytest.mark.parametrize(("path", "name", "job"), PUBLISHING_JOBS)
def test_a_job_that_publishes_an_image_runs_for_main_only(path, name, job):
    assert job.get("if") == MAIN_ONLY


@pytest.mark.parametrize("path", PUBLISHING_WORKFLOWS)
class TestPublishingWorkflowTriggers:
    def test_it_is_started_only_by_a_push_a_schedule_or_a_manual_run(self, path):
        assert set(_triggers(_load(path))) <= PUBLISH_TRIGGERS

    def test_a_push_that_starts_it_is_to_main_alone(self, path):
        push = _triggers(_load(path)).get("push") or {}
        assert push.get("branches") == ["main"]
        assert not {"branches-ignore", "tags", "tags-ignore"} & set(push)
