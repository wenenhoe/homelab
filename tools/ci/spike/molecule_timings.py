#!/usr/bin/env python3
"""Spike: where a pull request run's time goes, and what splitting Molecule roles further would save.

Run as the last job of a throwaway PR that forces every Molecule role. It reads
the run's jobs from the Actions API and the per-scenario timings each Molecule
leg uploaded, then prints a markdown report: queue wait and run time per job,
peak concurrent jobs and how long the run sat at the plan's cap, the fixed cost
of a Molecule leg, each leg's time, and for each role the projected time of its
slowest shard if its scenarios were dealt across 2, 3 or 4 legs.

Usage (from tools/): python3 -m ci.spike.molecule_timings <timings-dir> [<traces-dir>]
With a traces dir it appends the per-phase report from ci.spike.molecule_phases.
Needs GH_TOKEN, GITHUB_REPOSITORY and GITHUB_RUN_ID, and `gh` on PATH.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from ci.spike import molecule_phases

CAP = 20  # concurrent jobs on the GitHub Free plan
SHARDS = (2, 3, 4)
SELF = "spike-timings"
LEG = re.compile(r"^molecule \((?P<leg>[^)]+)\)$")

Row = tuple[str, str, str, int, str]  # leg, role, scenario, seconds, result


def parse_time(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text.replace("Z", "+00:00")) if text else None


def seconds(start: datetime | None, end: datetime | None) -> float | None:
    return (end - start).total_seconds() if start and end else None


def parse_jobs(lines: list[str]) -> list[dict]:
    """One JSON job object per line, as `gh api --jq '.jobs[]'` prints them. Jobs that never ran are dropped."""
    jobs = []
    for line in lines:
        if not line.strip():
            continue
        raw = json.loads(line)
        started, completed = parse_time(raw.get("started_at")), parse_time(raw.get("completed_at"))
        if not started or not completed or raw["name"] == SELF or raw.get("conclusion") == "skipped":
            continue
        steps = [
            {"name": s["name"], "seconds": seconds(parse_time(s.get("started_at")), parse_time(s.get("completed_at"))) or 0.0} for s in raw.get("steps", [])
        ]
        jobs.append(
            {
                "name": raw["name"],
                "created": parse_time(raw["created_at"]),
                "started": started,
                "completed": completed,
                "conclusion": raw.get("conclusion"),
                "steps": steps,
            }
        )
    return jobs


def queued(job: dict) -> float:
    return max(seconds(job["created"], job["started"]) or 0.0, 0.0)


def ran(job: dict) -> float:
    return seconds(job["started"], job["completed"]) or 0.0


def concurrency(jobs: list[dict], cap: int = CAP) -> tuple[int, float]:
    """(peak number of jobs running at once, seconds spent with at least `cap` running)."""
    events = sorted([(j["started"], 1) for j in jobs] + [(j["completed"], -1) for j in jobs], key=lambda e: (e[0], e[1]))
    running = peak = 0
    at_cap = 0.0
    previous = None
    for when, delta in events:
        if previous is not None and running >= cap:
            at_cap += (when - previous).total_seconds()
        running += delta
        peak = max(peak, running)
        previous = when
    return peak, at_cap


def leg_split(job: dict) -> tuple[float, float]:
    """(seconds in the step that runs the scenarios, seconds in everything else the leg does)."""
    scenarios = sum(s["seconds"] for s in job["steps"] if s["name"].startswith("Run molecule test"))
    return scenarios, max(ran(job) - scenarios, 0.0)


def read_timings(directory: Path) -> list[Row]:
    """Rows from every `timings-<leg>.tsv`; the file name says which leg ran them."""
    rows = []
    for path in sorted(directory.glob("*.tsv")):
        leg = path.stem.removeprefix("timings-")
        for line in path.read_text().splitlines():
            role, scenario, secs, result = line.split("\t")
            rows.append((leg, role, scenario, int(secs), result))
    return rows


def split_makespan(durations: list[int], shards: int) -> int:
    """Longest bin when the scenarios are dealt to `shards` bins, longest first into the emptiest bin."""
    bins = [0] * min(shards, max(len(durations), 1))
    for d in sorted(durations, reverse=True):
        bins[bins.index(min(bins))] += d
    return max(bins)


def fmt(secs: float) -> str:
    secs = round(secs)
    return f"{secs // 60}m{secs % 60:02d}s"


def render(jobs: list[dict], rows: list[Row], run_started: datetime | None) -> str:
    out = ["## Run timing spike", ""]
    end = max(j["completed"] for j in jobs)
    peak, at_cap = concurrency(jobs)
    out += [
        f"- Wall time from run start to last job: **{fmt(seconds(run_started, end) or 0)}**",
        f"- Jobs: {len(jobs)}; total runner time {fmt(sum(ran(j) for j in jobs))}; total queue wait {fmt(sum(queued(j) for j in jobs))}",
        f"- Peak concurrent jobs: **{peak}**; time with {CAP} or more running: **{fmt(at_cap)}**",
        "",
        "### Jobs by run time",
        "",
        "| Job | Queued | Ran | Result |",
        "| :--- | ---: | ---: | :--- |",
    ]
    out += [f"| {j['name']} | {fmt(queued(j))} | {fmt(ran(j))} | {j['conclusion']} |" for j in sorted(jobs, key=ran, reverse=True)]

    legs = {m["leg"]: j for j in jobs if (m := LEG.match(j["name"]))}
    overheads = [leg_split(j)[1] for j in legs.values()]
    overhead = statistics.median(overheads) if overheads else 0.0
    out += ["", f"### Molecule legs (median fixed cost per leg: {fmt(overhead)})", ""]
    by_leg: dict[str, list[int]] = {}
    for leg, _, _, secs, _ in rows:
        by_leg.setdefault(leg, []).append(secs)
    out += ["| Leg | Scenarios | Leg time | Scenario step | Fixed | Queued |", "| :--- | ---: | ---: | ---: | ---: | ---: |"]
    for leg in sorted(legs, key=lambda name: ran(legs[name]), reverse=True):
        job = legs[leg]
        scenario_step, fixed = leg_split(job)
        out += [f"| {leg} | {len(by_leg.get(leg, []))} | {fmt(ran(job))} | {fmt(scenario_step)} | {fmt(fixed)} | {fmt(queued(job))} |"]

    out += ["", "### Roles: projected slowest leg if all of a role's scenarios were dealt across N legs", ""]
    by_role: dict[str, list[int]] = {}
    legs_of_role: dict[str, set[str]] = {}
    for leg, role, _, secs, _ in rows:
        by_role.setdefault(role, []).append(secs)
        legs_of_role.setdefault(role, set()).add(leg)
    out += [
        "| Role | Legs | Scenarios | Sum of scenarios | Slowest leg now | " + " | ".join(f"Split {k}" for k in SHARDS) + " |",
        "| :--- | ---: | ---: | ---: | ---: | " + " | ".join("---:" for _ in SHARDS) + " |",
    ]
    for role in sorted(by_role, key=lambda r: sum(by_role[r]), reverse=True):
        now = max(ran(legs[leg]) for leg in legs_of_role[role] if leg in legs)
        splits = " | ".join(fmt(overhead + split_makespan(by_role[role], k)) for k in SHARDS)
        out += [f"| {role} | {len(legs_of_role[role])} | {len(by_role[role])} | {fmt(sum(by_role[role]))} | {fmt(now)} | {splits} |"]
    out += [
        "",
        "Split N = median fixed cost plus the longest of N legs, scenarios dealt longest-first. It ignores the coverage merge, which runs once either way.",
        "",
    ]

    out += ["### Scenarios", "", "| Leg | Scenario | Seconds | Result |", "| :--- | :--- | ---: | :--- |"]
    out += [f"| {leg} | {role}/{scenario} | {t} | {res} |" for leg, role, scenario, t, res in sorted(rows, key=lambda row: row[3], reverse=True)]
    return "\n".join(out) + "\n"


def fetch_jobs(repo: str, run_id: str) -> list[str]:
    result = subprocess.run(
        ["gh", "api", "--paginate", f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100&filter=latest", "--jq", ".jobs[]"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()


def fetch_run_started(repo: str, run_id: str) -> datetime | None:
    result = subprocess.run(["gh", "api", f"repos/{repo}/actions/runs/{run_id}", "--jq", ".run_started_at"], check=True, capture_output=True, text=True)
    return parse_time(result.stdout.strip())


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) not in (1, 2):
        print(__doc__, file=sys.stderr)
        return 2
    repo, run_id = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_RUN_ID"]
    report = render(parse_jobs(fetch_jobs(repo, run_id)), read_timings(Path(args[0])), fetch_run_started(repo, run_id))
    if len(args) == 2:
        report += "\n" + molecule_phases.render(molecule_phases.read_traces(Path(args[1])))
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as handle:
            handle.write(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
