"""Spike: split each Molecule scenario's time into Molecule's phases and find the slowest Ansible tasks.

Reads the traces ansible/scripts/molecule-test-all.sh writes when
MOLECULE_TRACE_DIR is set: `<role>/<scenario>.log`, one line of scenario output
per row with its epoch timestamp, a tab, then the line.

Two things in that output carry the timing:

- Molecule brackets each phase as `[<scenario> > <action>] Executing` and
  `[<scenario> > <action>] Executed: <result>`.
- The `ansible.posix.profile_tasks` callback closes every playbook run with a
  `TASKS RECAP` block of `<task> ----- <seconds>s` lines. It prints only the
  slowest tasks of each run (20 by default), so a task's total here is a floor.

A task run from a role prints as `<role> : <task>`, which is how the tasks of
molecule_helpers are told apart from a scenario's own.
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

HELPER_PREFIX = "molecule_helpers : "
TOP_TASKS = 25
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
MARKER = re.compile(r"\[(?P<scenario>\S+) > (?P<action>[a-z-]+)\] (?P<edge>Executing|Executed)\b")
RECAP_TASK = re.compile(r"^(?P<task>.+?) -+ ?(?P<seconds>\d+\.\d{2})s$")
PULL = re.compile(r"\bpull", re.IGNORECASE)
FINAL_DESTROY = "destroy (final)"
# What a scenario pays whatever the role under test does.
FIXED_PHASES = ("dependency", "destroy", "syntax", "create", FINAL_DESTROY)
ORDER = ("dependency", "destroy", "syntax", "create", "prepare", "converge", "idempotence", "verify", "cleanup", FINAL_DESTROY)

Line = tuple[float, str]


@dataclass
class Scenario:
    role: str
    name: str
    total: float = 0.0
    phases: dict[str, float] = field(default_factory=dict)
    tasks: list[tuple[str, str, float]] = field(default_factory=list)  # phase, task, seconds

    @property
    def other(self) -> float:
        """Time outside every phase: Molecule's own start-up and the gaps between phases."""
        return max(self.total - sum(self.phases.values()), 0.0)


def read_lines(path: Path) -> list[Line]:
    lines = []
    for raw in path.read_text(errors="replace").splitlines():
        stamp, _, text = raw.partition("\t")
        try:
            lines.append((float(stamp), ANSI.sub("", text)))
        except ValueError:
            continue
    return lines


def parse_scenario(role: str, name: str, lines: list[Line]) -> Scenario:
    """Phase seconds and recap tasks of one scenario's trace.

    A phase still open when the trace ends (the run died inside it) is closed at
    the last line. A second `destroy` after `create` began is the teardown, not
    the clean-up before the run, and is labelled apart.
    """
    scenario = Scenario(role, name)
    if not lines:
        return scenario
    scenario.total = lines[-1][0] - lines[0][0]
    open_phase: tuple[str, float] | None = None
    created = False
    in_recap = False
    for stamp, text in lines:
        marker = MARKER.search(text)
        if marker:
            action = marker["action"]
            if marker["edge"] == "Executing":
                created = created or action == "create"
                label = FINAL_DESTROY if action == "destroy" and created else action
                open_phase = (label, stamp)
            elif open_phase:
                label, started = open_phase
                scenario.phases[label] = scenario.phases.get(label, 0.0) + stamp - started
                open_phase = None
            in_recap = False
            continue
        if text.startswith("TASKS RECAP"):
            in_recap = True
            continue
        if in_recap:
            recap = RECAP_TASK.match(text)
            if recap:
                scenario.tasks.append((open_phase[0] if open_phase else "", recap["task"], float(recap["seconds"])))
            elif not (text.startswith("=") or re.match(r"^\w+ \d{2} \w+ \d{4} ", text)):
                in_recap = False
    if open_phase:
        label, started = open_phase
        scenario.phases[label] = scenario.phases.get(label, 0.0) + lines[-1][0] - started
    return scenario


def read_traces(directory: Path) -> list[Scenario]:
    """One Scenario per `<role>/<scenario>.log` under `directory`."""
    return [parse_scenario(path.parent.name, path.stem, read_lines(path)) for path in sorted(directory.glob("*/*.log"))]


def fmt(seconds: float) -> str:
    seconds = round(seconds)
    return f"{seconds // 60}m{seconds % 60:02d}s"


def phase_rows(scenarios: list[Scenario]) -> list[tuple[str, int, float, float, float]]:
    """(phase, scenarios that ran it, total seconds, median seconds, longest seconds), in test order."""
    by_phase: dict[str, list[float]] = defaultdict(list)
    for scenario in scenarios:
        for label, seconds in scenario.phases.items():
            by_phase[label].append(seconds)
    labels = sorted(by_phase, key=lambda label: (ORDER.index(label) if label in ORDER else len(ORDER), label))
    return [(label, len(by_phase[label]), sum(by_phase[label]), statistics.median(by_phase[label]), max(by_phase[label])) for label in labels]


def task_rows(scenarios: list[Scenario], keep) -> list[tuple[str, int, float, float]]:
    """(task, scenarios it shows up in, total seconds, longest seconds) for the tasks `keep` accepts, biggest total first."""
    seen: dict[str, list[float]] = defaultdict(list)
    for scenario in scenarios:
        per_scenario: dict[str, float] = defaultdict(float)
        for _, task, seconds in scenario.tasks:
            if keep(task):
                per_scenario[task] += seconds
        for task, seconds in per_scenario.items():
            seen[task].append(seconds)
    rows = [(task, len(times), sum(times), max(times)) for task, times in seen.items()]
    return sorted(rows, key=lambda row: row[2], reverse=True)


def render(scenarios: list[Scenario]) -> str:
    if not scenarios:
        return "## Molecule phase timing\n\nNo scenario traces were uploaded.\n"
    grand = sum(s.total for s in scenarios)
    out = ["## Molecule phase timing", "", f"{len(scenarios)} scenarios, {fmt(grand)} of scenario time in total (the legs' fixed setup is not included).", ""]

    out += ["### Time by phase, all scenarios", "", "| Phase | Scenarios | Total | Share | Median | Longest |", "| :--- | ---: | ---: | ---: | ---: | ---: |"]
    for label, count, total, median, longest in phase_rows(scenarios):
        out += [f"| {label} | {count} | {fmt(total)} | {total / grand:.0%} | {fmt(median)} | {fmt(longest)} |"]
    other = sum(s.other for s in scenarios)
    out += [f"| between phases | {len(scenarios)} | {fmt(other)} | {other / grand:.0%} | | |", ""]

    fixed = sum(seconds for s in scenarios for label, seconds in s.phases.items() if label in FIXED_PHASES) + other
    out += [
        "### Cost every scenario pays, whatever its role does",
        "",
        f"`{'`, `'.join(FIXED_PHASES)}` and the gaps between phases add up to **{fmt(fixed)}** ({fixed / grand:.0%} of scenario time),"
        f" about {fmt(fixed / len(scenarios))} per scenario. That is the most hoisting or caching shared setup could return.",
        "",
    ]

    helpers = task_rows(scenarios, lambda task: task.startswith(HELPER_PREFIX))
    out += [
        "### Shared helper tasks (molecule_helpers), repeated per scenario",
        "",
        "| Task | Scenarios | Total | Longest |",
        "| :--- | ---: | ---: | ---: |",
    ]
    out += [f"| {task.removeprefix(HELPER_PREFIX)} | {count} | {fmt(total)} | {fmt(longest)} |" for task, count, total, longest in helpers[:TOP_TASKS]]
    out += [""]

    pulls = task_rows(scenarios, lambda task: bool(PULL.search(task)))
    out += ["### Tasks that pull images", "", "| Task | Scenarios | Total | Longest |", "| :--- | ---: | ---: | ---: |"]
    out += [f"| {task} | {count} | {fmt(total)} | {fmt(longest)} |" for task, count, total, longest in pulls[:TOP_TASKS]]
    out += [""]

    out += [
        "### Slowest tasks by total across scenarios",
        "",
        "profile_tasks lists only the slowest tasks of each run, so these totals are floors.",
        "",
        "| Task | Scenarios | Total | Longest |",
        "| :--- | ---: | ---: | ---: |",
    ]
    out += [f"| {task} | {count} | {fmt(total)} | {fmt(longest)} |" for task, count, total, longest in task_rows(scenarios, lambda _: True)[:TOP_TASKS]]
    out += [""]

    single = sorted(((s, phase, task, secs) for s in scenarios for phase, task, secs in s.tasks), key=lambda row: row[3], reverse=True)
    out += ["### Slowest single task runs", "", "| Scenario | Phase | Task | Seconds |", "| :--- | :--- | :--- | ---: |"]
    out += [f"| {s.role}/{s.name} | {phase} | {task} | {secs:.0f} |" for s, phase, task, secs in single[:TOP_TASKS]]
    out += [""]

    columns = [label for label in ORDER if any(label in s.phases for s in scenarios)]
    out += [
        "### Each scenario",
        "",
        "| Scenario | Total | " + " | ".join(columns) + " | between |",
        "| :--- | ---: | " + " | ".join("---:" for _ in columns) + " | ---: |",
    ]
    for s in sorted(scenarios, key=lambda s: s.total, reverse=True):
        cells = " | ".join(fmt(s.phases[label]) if label in s.phases else "" for label in columns)
        out += [f"| {s.role}/{s.name} | {fmt(s.total)} | {cells} | {fmt(s.other)} |"]
    return "\n".join(out) + "\n"
