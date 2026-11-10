"""The job unit starts the runner so that nothing a previous run wrote into the job's state directory is imported."""

from __future__ import annotations

import re
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[3] / "ansible/roles/cd_agent/templates/cd-agent-job.service.j2"


def test_the_runner_starts_without_the_user_site_or_the_working_directory_on_its_module_path() -> None:
    exec_start = re.search(r"^ExecStart=(\S+) (.*?) -m cd_agent\.run_job", TEMPLATE.read_text(), re.MULTILINE)

    assert exec_start is not None
    assert exec_start[1] == "/usr/bin/python3"
    assert set(exec_start[2].split()) == {"-s", "-P"}
