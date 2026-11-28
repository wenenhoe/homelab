"""python3 -m cloud_session.prepare

Prepare a Claude Code cloud session to run Molecule, as its SessionStart hook; it does nothing anywhere else
(docs/topics/engineering/hosted-sessions.md). It changes the session's machine and the checkout's own remote-tracking ref of its branch, and
nothing else in the repository.

Standard library only: it runs on the machine's own python3 before anything is installed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER_SOURCE = Path(__file__).with_name("runc_ca.py")
RUNTIME = "ca"
DAEMON_CONFIG = {"registry-mirrors": ["https://mirror.gcr.io"]}
DOMAIN = "localtest.me"
SCENARIO_NAME = re.compile(rf"\b[a-z0-9-]+\.{re.escape(DOMAIN)}\b")
# Run in the new mount namespace: cgroup2 over the machine's cgroup mount, then the daemon in place of the shell.
CGROUP2_THEN_RUN = 'mount -t cgroup2 none /sys/fs/cgroup && exec "$@"'
START_TIMEOUT_SECONDS = 60
GIT_SECONDS = 30


@dataclass(frozen=True)
class Machine:
    """The files of the session's machine that are read or written."""

    ca_bundle: Path = Path("/root/.ccr/ca-bundle.crt")
    daemon_json: Path = Path("/etc/docker/daemon.json")
    wrapper: Path = Path("/usr/local/bin/runc-ca")
    hosts: Path = Path("/etc/hosts")
    cgroup: Path = Path("/sys/fs/cgroup")
    pid_file: Path = Path("/var/run/docker.pid")
    processes: Path = Path("/proc")
    log: Path = Path("/var/log/cloud-session-dockerd.log")
    repo: Path = REPO_ROOT


def write_daemon_config(machine: Machine) -> str:
    if machine.daemon_json.exists():
        return f"{machine.daemon_json} exists and was left alone"
    machine.daemon_json.parent.mkdir(parents=True, exist_ok=True)
    machine.daemon_json.write_text(json.dumps(DAEMON_CONFIG) + "\n")
    return "registry mirror configured"


def install_wrapper(machine: Machine) -> bool:
    """Install the runtime wrapper, if the machine has a bundle for it to read."""
    if not machine.ca_bundle.is_file():
        return False
    shutil.copyfile(WRAPPER_SOURCE, machine.wrapper)
    machine.wrapper.chmod(0o755)
    return True


def scenario_names(repo: Path = REPO_ROOT) -> list[str]:
    """The names under the test domain that Molecule scenarios use, each with the OpenBao name beside it."""
    found: set[str] = set()
    for converge in repo.glob("ansible/roles/*/molecule/*/converge.yml"):
        found.update(SCENARIO_NAME.findall(converge.read_text()))
    return sorted(found | {f"openbao.{name}" for name in found})


def add_hosts(machine: Machine, names: list[str]) -> str:
    text = machine.hosts.read_text()
    present = {word for line in text.splitlines() for word in line.split("#")[0].split()[1:]}
    missing = [name for name in names if name not in present]
    if missing:
        machine.hosts.write_text(f"{text.rstrip()}\n127.0.0.1 {' '.join(missing)}\n")
    return f"{len(names)} scenario names resolve to 127.0.0.1"


def bypass_proxy(env_file: str | None) -> str:
    """Have the session's shell commands reach the test domain directly, not through the environment's proxy."""
    if not env_file:
        return f"CLAUDE_ENV_FILE is not set: add .{DOMAIN} to NO_PROXY and no_proxy by hand"
    path = Path(env_file)
    lines = [f'export {name}="${{{name}:+${name},}}.{DOMAIN}"' for name in ("NO_PROXY", "no_proxy")]
    written = path.read_text() if path.exists() else ""
    with path.open("a") as handle:
        handle.writelines(f"{line}\n" for line in lines if line not in written)
    return f".{DOMAIN} bypasses the proxy"


def drop_stale_tracking_ref(machine: Machine) -> str:
    """Drop `refs/remotes/origin/<branch>` of the checked-out branch when `origin` has no such branch.

    The session's stop hook counts the commits above that ref and asks for a push, which a session never makes (AGENTS.md): its work goes to
    the maintainer as a series file. The ref is only a local record, and a branch `origin` does have, or one that cannot be asked about, keeps it.
    """

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        # No prompt: a remote that asks for a login fails here instead of holding the hook.
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        return subprocess.run(["git", "-C", str(machine.repo), *args], capture_output=True, text=True, check=False, timeout=GIT_SECONDS, env=env)

    branch = git("branch", "--show-current")
    if branch.returncode != 0:
        return f"{machine.repo} is not a git checkout: no tracking ref to drop"
    name = branch.stdout.strip()
    if not name:
        return "HEAD is detached: no tracking ref to drop"
    ref = f"refs/remotes/origin/{name}"
    if git("rev-parse", "-q", "--verify", ref).returncode != 0:
        return f"{name} has no tracking ref"
    listed = git("ls-remote", "--exit-code", "origin", f"refs/heads/{name}")
    if listed.returncode == 0:
        return f"origin has {name}: its tracking ref was left alone"
    if listed.returncode != 2:  # `--exit-code` exits 2 only when the remote answered and has no such ref
        return f"origin could not be asked ({(listed.stderr.strip().splitlines() or ['no output'])[-1]}): the tracking ref of {name} was left alone"
    dropped = git("update-ref", "-d", ref)
    if dropped.returncode != 0:
        raise RuntimeError(dropped.stderr.strip())
    return f"{name} has no branch on origin: its tracking ref was dropped, so the stop hook has no push to ask for"


def docker_info() -> str | None:
    """The running daemon's default runtime, or None when no daemon answers."""
    done = subprocess.run(["docker", "info", "--format", "{{.DefaultRuntime}}"], capture_output=True, text=True, check=False, timeout=20)
    return done.stdout.strip() if done.returncode == 0 else None


def clear_stale_pid_file(machine: Machine) -> None:
    # A restored session keeps the file but not the process, and dockerd refuses to start while the number names any process.
    if not machine.pid_file.exists():
        return
    command = machine.processes / machine.pid_file.read_text().strip() / "comm"
    if not command.exists() or command.read_text().strip() != "dockerd":
        machine.pid_file.unlink()


def daemon_command(machine: Machine, wrapped: bool) -> list[str]:
    command = ["dockerd"]
    if wrapped:
        command += ["--add-runtime", f"{RUNTIME}={machine.wrapper}", "--default-runtime", RUNTIME]
    if not (machine.cgroup / "cgroup.controllers").exists():
        # cgroup v1: systemd in current images needs v2, so the daemon alone gets it, in its own mount namespace.
        command = ["unshare", "--mount", "--propagation", "private", "sh", "-c", CGROUP2_THEN_RUN, "sh", *command]
    return command


def start_docker(machine: Machine, wrapped: bool) -> str:
    runtime = docker_info()
    if runtime is not None:
        if wrapped and runtime != RUNTIME:
            raise RuntimeError("a dockerd without the certificate wrapper is already running; stop it and run this again")
        return "dockerd was already running"
    clear_stale_pid_file(machine)
    with machine.log.open("ab") as log:
        # Its own session and a log file, so it outlives the hook and holds none of the hook's pipes.
        daemon = subprocess.Popen(daemon_command(machine, wrapped), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.monotonic() + START_TIMEOUT_SECONDS
    while time.monotonic() < deadline and daemon.poll() is None:
        if docker_info() is not None:
            return "dockerd started"
        time.sleep(1)
    raise RuntimeError(f"dockerd did not start; see {machine.log}")


def prepare(machine: Machine, env_file: str | None) -> list[str]:
    """Each step's outcome. A step that fails says so and the rest still run."""
    report: list[str] = []
    wrapped = False
    try:
        wrapped = install_wrapper(machine)
        report.append("certificate wrapper installed" if wrapped else f"no {machine.ca_bundle}: containers run unwrapped")
    except OSError as error:
        report.append(f"FAILED to install the certificate wrapper: {error}")
    steps = (
        ("write the daemon config", lambda: write_daemon_config(machine)),
        ("add the scenario names", lambda: add_hosts(machine, scenario_names())),
        ("set NO_PROXY", lambda: bypass_proxy(env_file)),
        ("drop the stale tracking ref", lambda: drop_stale_tracking_ref(machine)),
        ("start dockerd", lambda: start_docker(machine, wrapped)),
    )
    for name, step in steps:
        try:
            report.append(step())
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            report.append(f"FAILED to {name}: {error}")
    return report


def main(environ: Mapping[str, str] = os.environ, machine: Machine | None = None) -> int:
    if environ.get("CLAUDE_CODE_REMOTE") != "true":
        return 0
    # The hook's output is read by the session, so a failure is reported there and the session starts all the same.
    print("Cloud session preparation:")
    for line in prepare(machine or Machine(), environ.get("CLAUDE_ENV_FILE")):
        print(f"- {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
