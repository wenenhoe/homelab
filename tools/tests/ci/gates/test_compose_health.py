"""Tests for ci.gates.compose_health, against a fake docker.

FakeDocker answers `docker compose config/ps` and `docker inspect` from a
description of the stack and records `docker logs` calls and sleeps, so
every path (healthy, unhealthy, never healthy, no healthcheck, crashed) runs
without docker and without waiting.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import io
import subprocess
from contextlib import redirect_stdout
from pathlib import Path

from ci.gates import compose_health as ch


class FakeDocker:
    def __init__(
        self,
        services: dict[str, list[str]],
        health: dict[str, list[str] | None] | None = None,
        running: dict[str, bool] | None = None,
        failing: tuple[str, ...] = (),
    ):
        self.services = services
        self.health = health or {}  # cid -> statuses in order (last repeats); None or absent = no healthcheck
        self.running = running or {}
        self.failing = failing
        self.logs: list[str] = []
        self.commands: list[list[str]] = []
        self.sleeps: list[float] = []
        self._polls: dict[str, int] = {}

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def __call__(self, args: list[str], cwd: Path, capture: bool = False) -> subprocess.CompletedProcess[str]:
        self.commands.append(args)
        joined = " ".join(args)
        if any(marker in joined for marker in self.failing):
            return subprocess.CompletedProcess(args, 1, stdout="")
        if args[1] == "compose" or args[:2] == ["docker", "compose"]:
            if "--services" in args:
                return self._ok(args, "\n".join(self.services))
            return self._ok(args, "\n".join(self.services[args[-1]]))
        if args[1] == "logs":
            self.logs.append(args[2])
            return self._ok(args, "")
        cid, fmt = args[-1], args[2]
        if "{{if .State.Health}}" in fmt:
            return self._ok(args, "yes" if self.health.get(cid) else "")
        if "Health.Status" in fmt:
            statuses = self.health[cid]
            index = self._polls.get(cid, 0)
            self._polls[cid] = index + 1
            return self._ok(args, statuses[min(index, len(statuses) - 1)])
        return self._ok(args, "true" if self.running.get(cid, True) else "false")

    @staticmethod
    def _ok(args: list[str], stdout: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, stdout=stdout + "\n")

    def polls(self, cid: str) -> int:
        return self._polls.get(cid, 0)


def run_wait(docker: FakeDocker) -> tuple[int, str]:
    out = io.StringIO()
    with redirect_stdout(out):
        code = ch.wait("compose.yaml", docker, docker.sleep)
    return code, out.getvalue()


class TestHealthcheck:
    def test_healthy_on_the_first_check_passes_without_sleeping(self):
        docker = FakeDocker({"web": ["c1"]}, health={"c1": ["healthy"]})
        assert run_wait(docker)[0] == 0
        assert docker.sleeps == []

    def test_starting_then_healthy_waits_between_checks(self):
        docker = FakeDocker({"web": ["c1"]}, health={"c1": ["starting", "starting", "healthy"]})
        code, out = run_wait(docker)
        assert code == 0
        assert docker.sleeps == [2.0, 2.0]
        assert "Waiting for web to report healthy" in out

    def test_unhealthy_fails_immediately_and_prints_the_logs(self):
        docker = FakeDocker({"web": ["c1"]}, health={"c1": ["starting", "unhealthy"]})
        code, out = run_wait(docker)
        assert code == 1
        assert "::error::web is unhealthy" in out
        assert docker.logs == ["c1"]
        assert docker.polls("c1") == 2

    def test_never_healthy_gives_up_after_thirty_checks_naming_the_last_status(self):
        docker = FakeDocker({"web": ["c1"]}, health={"c1": ["starting"]})
        code, out = run_wait(docker)
        assert code == 1
        assert "::error::web never became healthy (last: starting)" in out
        assert docker.polls("c1") == ch.HEALTH_CHECKS
        assert len(docker.sleeps) == ch.HEALTH_CHECKS - 1
        assert docker.logs == ["c1"]

    def test_becoming_healthy_on_the_last_check_still_passes(self):
        docker = FakeDocker({"web": ["c1"]}, health={"c1": ["starting"] * (ch.HEALTH_CHECKS - 1) + ["healthy"]})
        assert run_wait(docker)[0] == 0


class TestNoHealthcheck:
    def test_still_running_after_the_grace_period_passes(self):
        docker = FakeDocker({"web": ["c1"]}, running={"c1": True})
        assert run_wait(docker)[0] == 0
        assert docker.sleeps == [10.0]

    def test_exited_during_the_grace_period_fails_with_logs(self):
        docker = FakeDocker({"web": ["c1"]}, running={"c1": False})
        code, out = run_wait(docker)
        assert code == 1
        assert "::error::web exited unexpectedly" in out
        assert docker.logs == ["c1"]

    def test_an_empty_health_state_means_no_healthcheck(self):
        docker = FakeDocker({"web": ["c1"]}, health={"c1": None})
        assert run_wait(docker)[0] == 0
        assert docker.sleeps == [10.0]


class TestStack:
    def test_a_service_with_no_container_never_started(self):
        docker = FakeDocker({"web": []})
        code, out = run_wait(docker)
        assert code == 1
        assert "::error::web never started" in out
        assert docker.logs == []

    def test_services_are_checked_in_order_and_the_first_failure_stops_the_rest(self):
        docker = FakeDocker({"db": ["c1"], "web": ["c2"], "cache": ["c3"]}, health={"c1": ["healthy"], "c2": ["unhealthy"], "c3": ["healthy"]})
        assert run_wait(docker)[0] == 1
        assert docker.polls("c3") == 0

    def test_every_service_must_pass(self):
        docker = FakeDocker({"db": ["c1"], "web": ["c2"]}, health={"c1": ["healthy"], "c2": None})
        assert run_wait(docker)[0] == 0
        assert docker.polls("c1") == 1
        assert docker.sleeps == [10.0]

    def test_a_scaled_service_has_every_container_checked(self):
        docker = FakeDocker({"web": ["c1", "c2"]}, health={"c1": ["healthy"], "c2": ["unhealthy"]})
        code, out = run_wait(docker)
        assert code == 1
        assert docker.logs == ["c2"]
        assert "web is unhealthy" in out

    def test_the_compose_file_is_passed_to_every_compose_command(self):
        docker = FakeDocker({"web": ["c1"]}, health={"c1": ["healthy"]})
        run_wait(docker)
        compose = [args for args in docker.commands if args[1] == "compose"]
        assert compose
        assert all(args[2:4] == ["-f", "compose.yaml"] for args in compose)

    def test_a_stack_with_no_services_passes(self):
        assert run_wait(FakeDocker({}))[0] == 0


class TestDockerFailure:
    def test_failing_to_list_services_is_an_error(self):
        code, out = run_wait(FakeDocker({"web": ["c1"]}, failing=("--services",)))
        assert code == 1
        assert "::error::`docker compose -f compose.yaml config --services` exited 1" in out

    def test_a_failing_inspect_is_an_error_not_a_pass(self):
        code, out = run_wait(FakeDocker({"web": ["c1"]}, health={"c1": ["healthy"]}, failing=("inspect",)))
        assert code == 1
        assert "docker inspect" in out

    def test_main_takes_the_compose_file_from_the_command_line(self):
        docker = FakeDocker({"web": ["c1"]}, health={"c1": ["healthy"]})
        with redirect_stdout(io.StringIO()):
            assert ch.main(["/tmp/x/compose.yaml"], docker, docker.sleep) == 0
        assert docker.commands[0][2:4] == ["-f", "/tmp/x/compose.yaml"]
