"""Tests for cd_agent/toolchain.py against real uv and a real, dependency-free project.

The command under test replaces the toolchain process, so every case runs it
as a subprocess. Run via `uv run pytest tools/tests/cd_agent/ -v`.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from cd_agent import toolchain
from cd_agent.toolchain import ToolchainError

TOOLS = Path(__file__).resolve().parents[2]
PYPROJECT = '[project]\nname = "probe"\nversion = "0"\nrequires-python = ">=3.9"\ndependencies = []\n\n[tool.uv]\npackage = false\n'
SHOW_ENV = "import os; print(os.environ['VIRTUAL_ENV']); print(os.environ['PATH'].split(os.pathsep)[0]); print(os.environ.get('ANSIBLE_COLLECTIONS_PATH', '-'))"


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A checkout root holding a locked project, with an `ansible/` subdirectory to run from."""
    root = tmp_path / "tree"
    (root / "ansible").mkdir(parents=True)
    (root / "pyproject.toml").write_text(PYPROJECT)
    subprocess.run(["uv", "lock", "--offline", "--project", str(root)], check=True, capture_output=True)
    return root


@pytest.fixture
def state(tmp_path: Path) -> Path:
    return tmp_path / "state"


@pytest.fixture
def stub_galaxy(tmp_path: Path) -> Path:
    """A directory with an `ansible-galaxy` that logs its arguments and exits with $STUB_GALAXY_EXIT."""
    directory = tmp_path / "stub-bin"
    directory.mkdir()
    script = directory / "ansible-galaxy"
    script.write_text('#!/bin/sh\necho "$@" >> "$STUB_GALAXY_LOG"\nexit "${STUB_GALAXY_EXIT:-0}"\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return directory


@pytest.fixture
def logging_uv(tmp_path: Path) -> Path:
    """A directory with a `uv` that logs its arguments to $STUB_UV_LOG, then runs the real one."""
    directory = tmp_path / "logging-uv-bin"
    directory.mkdir()
    script = directory / "uv"
    script.write_text('#!/bin/sh\necho "$@" >> "$STUB_UV_LOG"\nexec "$REAL_UV" "$@"\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return directory


def run_toolchain(cwd: Path, state: Path | None, *args: str, extra_path: Path | None = None, **env: str) -> subprocess.CompletedProcess[str]:
    base = {k: v for k, v in os.environ.items() if k != "CD_AGENT_STATE_DIR"}
    base["PYTHONPATH"] = str(TOOLS)
    base["PATH"] = f"{extra_path}{os.pathsep}{base['PATH']}" if extra_path else base["PATH"]
    if state is not None:
        base["CD_AGENT_STATE_DIR"] = str(state)
    return subprocess.run([sys.executable, "-m", "cd_agent.toolchain", *args], cwd=cwd, env={**base, **env}, capture_output=True, text=True, check=False)


def command(code: str = SHOW_ENV) -> tuple[str, ...]:
    return ("--", sys.executable, "-c", code)


class TestFindRoot:
    def test_finds_the_nearest_directory_holding_the_lock(self, checkout):
        assert toolchain.find_root(checkout / "ansible") == checkout

    def test_prefers_the_nearest_lock_over_a_higher_one(self, checkout):
        (checkout / "ansible" / "uv.lock").write_text("")

        assert toolchain.find_root(checkout / "ansible") == checkout / "ansible"

    def test_fails_when_no_lock_exists_above(self, tmp_path):
        with pytest.raises(ToolchainError, match=r"no uv\.lock"):
            toolchain.find_root(tmp_path)


class TestEnvironment:
    def test_builds_the_venv_in_the_jobs_state_directory_and_runs_the_command_with_it(self, checkout, state):
        result = run_toolchain(checkout / "ansible", state, *command())

        venv = state / "toolchain" / "venv"
        assert (result.returncode, result.stdout.splitlines()) == (0, [str(venv), str(venv / "bin"), "-"])
        assert (venv / "bin" / "python").exists()

    def test_the_commands_exit_status_is_the_jobs(self, checkout, state):
        result = run_toolchain(checkout / "ansible", state, *command("raise SystemExit(7)"))

        assert result.returncode == 7

    def test_a_second_run_reuses_the_environment(self, checkout, state):
        run_toolchain(checkout / "ansible", state, *command())
        marker = state / "toolchain" / "venv" / "marker"
        marker.write_text("kept")

        second = run_toolchain(checkout / "ansible", state, *command())

        assert (second.returncode, marker.read_text()) == (0, "kept")

    def test_the_environment_holds_exactly_what_the_lock_names(self, checkout, state):
        run_toolchain(checkout / "ansible", state, *command())
        site = next((state / "toolchain" / "venv" / "lib").glob("python*/site-packages"))
        record = site / "stray_package-1.0.dist-info"
        record.mkdir()
        (record / "METADATA").write_text("Metadata-Version: 2.1\nName: stray-package\nVersion: 1.0\n")
        (record / "INSTALLER").write_text("pip\n")
        (record / "RECORD").write_text("stray_package.py,,\nstray_package-1.0.dist-info/METADATA,,\nstray_package-1.0.dist-info/RECORD,,\n")
        stray = site / "stray_package.py"
        stray.write_text("")

        run_toolchain(checkout / "ansible", state, *command())

        assert not stray.exists()

    def test_a_lock_that_no_longer_matches_pyproject_stops_the_run(self, checkout, state):
        (checkout / "pyproject.toml").write_text(PYPROJECT.replace("dependencies = []", 'dependencies = ["package-the-lock-does-not-know"]'))
        marker = state / "ran"

        result = run_toolchain(checkout / "ansible", state, *command(f"open({str(marker)!r}, 'w')"))

        assert (result.returncode, marker.exists(), "uv sync" in result.stderr) == (1, False, True)

    def test_installs_without_development_dependencies_and_only_from_the_lock(self, checkout, state, logging_uv, tmp_path):
        log = tmp_path / "uv.log"

        run_toolchain(checkout / "ansible", state, *command(), extra_path=logging_uv, STUB_UV_LOG=str(log), REAL_UV=shutil.which("uv"))

        (invocation,) = log.read_text().splitlines()
        assert invocation.split()[:4] == ["sync", "--locked", "--no-dev", "--project"]

    def test_the_cache_stays_inside_the_state_directory(self, checkout, state):
        run_toolchain(checkout / "ansible", state, *command())

        assert (state / "toolchain" / "uv-cache").is_dir()


class TestCollections:
    def test_installs_the_named_requirements_into_the_state_directory_and_exposes_them(self, checkout, state, stub_galaxy, tmp_path):
        (checkout / "ansible" / "requirements.yml").write_text("collections: []\n")
        log = tmp_path / "galaxy.log"

        result = run_toolchain(checkout / "ansible", state, "--collections", "requirements.yml", *command(), extra_path=stub_galaxy, STUB_GALAXY_LOG=str(log))

        collections = state / "toolchain" / "collections"
        assert result.returncode == 0
        assert log.read_text().split() == ["collection", "install", "-r", str(checkout / "ansible" / "requirements.yml"), "-p", str(collections)]
        assert result.stdout.splitlines()[2] == str(collections)

    def test_without_the_option_no_collection_step_runs(self, checkout, state, stub_galaxy, tmp_path):
        log = tmp_path / "galaxy.log"

        run_toolchain(checkout / "ansible", state, *command(), extra_path=stub_galaxy, STUB_GALAXY_LOG=str(log))

        assert not log.exists()

    def test_a_failed_install_stops_the_run(self, checkout, state, stub_galaxy, tmp_path):
        (checkout / "ansible" / "requirements.yml").write_text("collections: []\n")
        marker = state / "ran"

        result = run_toolchain(
            checkout / "ansible",
            state,
            "--collections",
            "requirements.yml",
            *command(f"open({str(marker)!r}, 'w')"),
            extra_path=stub_galaxy,
            STUB_GALAXY_LOG=str(tmp_path / "galaxy.log"),
            STUB_GALAXY_EXIT="1",
        )

        assert (result.returncode, marker.exists()) == (1, False)

    @pytest.mark.parametrize("requirements", ["../../outside.yml", "/etc/hostname"])
    def test_refuses_a_requirements_file_outside_the_checkout(self, checkout, state, stub_galaxy, tmp_path, requirements):
        result = run_toolchain(
            checkout / "ansible", state, "--collections", requirements, *command(), extra_path=stub_galaxy, STUB_GALAXY_LOG=str(tmp_path / "g.log")
        )

        assert (result.returncode, "leaves the checkout" in result.stderr) == (1, True)


class TestRefusals:
    def test_needs_the_state_directory_the_runner_sets(self, checkout):
        result = run_toolchain(checkout / "ansible", None, *command())

        assert (result.returncode, "CD_AGENT_STATE_DIR is not set" in result.stderr) == (1, True)

    def test_needs_uv_on_path(self, checkout, state, tmp_path):
        no_uv = tmp_path / "no-uv"
        no_uv.mkdir()
        python = no_uv / "python"
        python.symlink_to(sys.executable)
        env = {"CD_AGENT_STATE_DIR": str(state), "PYTHONPATH": str(TOOLS), "PATH": str(no_uv)}

        result = subprocess.run(
            [str(python), "-m", "cd_agent.toolchain", *command()], cwd=checkout / "ansible", env=env, capture_output=True, text=True, check=False
        )

        assert (result.returncode, "uv not found on PATH" in result.stderr) == (1, True)

    def test_needs_a_lock_above_the_working_directory(self, tmp_path, state):
        empty = tmp_path / "empty"
        empty.mkdir()

        result = run_toolchain(empty, state, *command())

        assert (result.returncode, "no uv.lock" in result.stderr) == (1, True)

    def test_a_command_that_cannot_start_is_an_error(self, checkout, state):
        result = run_toolchain(checkout / "ansible", state, "--", "no-such-program-for-cd-agent")

        assert (result.returncode, "cannot start 'no-such-program-for-cd-agent'" in result.stderr) == (1, True)

    @pytest.mark.parametrize(
        "argv",
        [
            pytest.param(["--collections", "r.yml", "true"], id="no-separator"),
            pytest.param(["--"], id="empty-command"),
        ],
    )
    def test_a_malformed_invocation_is_a_usage_error(self, argv):
        with pytest.raises(SystemExit) as raised:
            toolchain.main(argv)

        assert raised.value.code == 2


def test_uv_is_available_to_these_tests():
    assert shutil.which("uv") is not None
