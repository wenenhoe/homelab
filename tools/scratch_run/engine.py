"""Runs a spec's steps against a backend and writes what came out.

The engine is the part that does not change with where the gateway runs. A backend builds the gateway, runs one
step at a time and removes it; it answers each call with the exit status and the output the command printed. The
engine decides from those whether the step had the outcome the spec expected, writes one file per step, checks the
files for credential values, and bundles them into one archive to hand back.
"""

from __future__ import annotations

import json
import re
import tarfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from scratch_run.spec import Spec, Step

RECAP_RE = re.compile(r"^localhost +:.*\bchanged=(\d+)\b", re.MULTILINE)
FLOW_FAILED_RE = re.compile(r"^FAIL ", re.MULTILINE)
MIN_SECRET_LENGTH = 8  # a shorter value would match ordinary text
EXIT_OK, EXIT_STEP_FAILED, EXIT_NOT_RUN = 0, 1, 2
RUNNER_NOTHING_SELECTED = 2  # network_checks.runner's status for a selection that holds no flow


class Backend(Protocol):
    """Where the gateway runs. Each call answers with (exit status, output)."""

    def preflight(self, spec: Spec) -> list[str]:
        """Every precondition that is missing, as a sentence each; empty when the run can start."""

    def up(self, spec: Spec) -> tuple[int, str]: ...

    def play(self, spec: Spec, mode: str) -> tuple[int, str]: ...

    def flows(self, tags: tuple[str, ...], ids: tuple[str, ...]) -> tuple[int, str]: ...

    def block(self, spec: Spec, state: str) -> tuple[int, str]: ...

    def logs(self) -> dict[str, str]:
        """The log files the gateway's build left behind, by file name, for the results to keep. Called before `down`."""

    def down(self) -> tuple[int, str]:
        """Remove everything `up` and the steps made. Safe to call after a failed `up`."""

    def secrets(self) -> list[str]:
        """The credential values of this run, which no result file may hold."""


@dataclass(frozen=True)
class Outcome:
    id: str
    kind: str
    detail: str
    passed: bool
    seconds: float


def judge(step: Step, status: int, output: str) -> tuple[bool, str]:
    """Whether a step had the outcome the spec expected, and a line saying why."""
    if step.kind == "block":
        return status == 0, f"the playbook exited {status}"
    if step.kind == "flows":
        if step.expect == "pass":
            return status == 0, f"the runner exited {status}, wanted 0"
        # A runner that crashed also exits non-zero; only a flow it reports as failed is the failure wanted.
        failed_as_wanted = status not in (0, RUNNER_NOTHING_SELECTED) and FLOW_FAILED_RE.search(output) is not None
        return failed_as_wanted, f"the runner exited {status}, wanted a flow reported as failed" + (
            "" if failed_as_wanted else " (none was: they passed, none was selected, or the runner crashed)"
        )
    if status != 0:
        return False, f"the play exited {status}"
    if step.expect == "ok":
        return True, "the play exited 0"
    recap = RECAP_RE.search(output)
    if recap is None:
        return False, "the output has no recap line"
    changed = int(recap.group(1))
    if step.expect == "unchanged":
        return changed == 0, f"the recap says changed={changed}, wanted 0"
    return changed > 0, f"the recap says changed={changed}, wanted more than 0"


def _leaks(directory: Path, secrets: list[str]) -> list[str]:
    values = [value for value in secrets if len(value) >= MIN_SECRET_LENGTH]
    return sorted({path.name for path in directory.rglob("*") if path.is_file() for value in values if value in path.read_text(errors="replace")})


def _keep_logs(directory: Path, logs: dict[str, str]) -> None:
    """Write the build's log files under `directory`; a name is cut to its last part, so none can land outside it."""
    if not logs:
        return
    directory.mkdir(mode=0o700)
    for name, text in logs.items():
        (directory / Path(name).name).write_text(text)


def _bundle(directory: Path, archive: Path) -> None:
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(directory, arcname=directory.name)


def _results_md(spec: Spec, outcomes: list[Outcome], leaks: list[str]) -> str:
    lines = [f"# {spec.name}", "", spec.description, "", "| Step | Kind | Result | Detail | Seconds |", "| :--- | :--- | :--- | :--- | ---: |"]
    lines += [f"| `{o.id}` | {o.kind} | {'PASS' if o.passed else 'FAIL'} | {o.detail} | {o.seconds:.0f} |" for o in outcomes]
    if leaks:
        lines += ["", f"A credential value is in: {', '.join(leaks)}"]
    return "\n".join(lines) + "\n"


def run(spec: Spec, backend: Backend, out_dir: Path, stamp: str, clock: Callable[[], float], keep: bool = False, say: Callable[[str], None] = print) -> int:
    """Run the spec: 0 when every step had its expected outcome, 1 when one did not, 2 when the run could not start."""
    problems = backend.preflight(spec)
    if problems:
        say(f"{spec.name} was not started; {len(problems)} thing(s) are missing:")
        for problem in problems:
            say(f"  - {problem}")
        return EXIT_NOT_RUN
    results = out_dir / f"{spec.name}-{stamp}"
    results.mkdir(parents=True, mode=0o700)
    outcomes: list[Outcome] = []

    def record(step_id: str, kind: str, passed: bool, detail: str, started: float, output: str) -> None:
        (results / f"{step_id}.txt").write_text(output)
        seconds = clock() - started
        outcomes.append(Outcome(step_id, kind, detail, passed, seconds))
        say(f"STEP {step_id}: {'PASS' if passed else 'FAIL'} ({detail}; {seconds:.0f}s)")

    started = clock()
    say("STEP up: building the gateway (its log follows; this takes minutes)")
    status, output = backend.up(spec)
    record("up", "setup", status == 0, f"the gateway build exited {status}", started, output)
    if status == 0:
        for step in spec.steps:
            started = clock()
            say(f"STEP {step.id}: running ({step.kind} {step.mode or ','.join((*step.tags, *step.flow_ids))})")
            if step.kind == "play":
                status, output = backend.play(spec, step.mode)
            elif step.kind == "flows":
                status, output = backend.flows(step.tags, step.flow_ids)
            else:
                status, output = backend.block(spec, step.mode)
            passed, detail = judge(step, status, output)
            record(step.id, step.kind, passed, detail, started, output)
    _keep_logs(results / "logs", backend.logs())
    if keep:
        say("--keep: the gateway is still up; remove it with the backend's own down")
    else:
        started = clock()
        say("STEP down: removing the gateway")
        status, output = backend.down()
        record("down", "teardown", status == 0, f"the removal exited {status}", started, output)
    leaks = _leaks(results, backend.secrets())
    (results / "results.json").write_text(json.dumps([asdict(o) for o in outcomes], indent=1))
    (results / "results.md").write_text(_results_md(spec, outcomes, leaks))
    if leaks:
        say(f"A CREDENTIAL VALUE IS IN: {', '.join(leaks)}; no archive was written")
        return EXIT_STEP_FAILED
    archive = out_dir / f"results-{spec.name}-{stamp}.tgz"
    _bundle(results, archive)
    failed = [o.id for o in outcomes if not o.passed]
    say("\n".join(f"  {'PASS' if o.passed else 'FAIL'} {o.id:<20} {o.seconds:>5.0f}s" for o in outcomes))
    say(f"  total {sum(o.seconds for o in outcomes):.0f}s")
    say("ALL STEPS PASSED" if not failed else f"{len(failed)} STEP(S) FAILED: {', '.join(failed)}")
    say(f"results: {archive}")
    return EXIT_OK if not failed else EXIT_STEP_FAILED
