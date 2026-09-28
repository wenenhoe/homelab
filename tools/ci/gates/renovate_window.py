#!/usr/bin/env python3
"""Did a scheduled Renovate run start inside its PR-creation window?

renovate.json5's `schedule` only lets Renovate open new branches and PRs
inside a window (cron syntax, in its `timezone`). GitHub starts a scheduled
run some unpredictable time after the cron tick, so a run can land after
the window has closed and silently open nothing while the job still
succeeds. This check turns that into a failure.

Both the timezone and every `schedule:` are read from renovate.json5, so
changing the window there changes what this checks. A run fails when it
started on a day the schedule has a window, but outside that window's hours;
on a day with no window nothing is expected of it. Only a scheduled run
belongs here: a manual run isn't waiting on a cron tick.

Usage (from tools/): python -m ci.gates.renovate_window <started-epoch>
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

REPO_ROOT = Path(__file__).resolve().parents[3]
RENOVATE_CONFIG = ".github/renovate.json5"

_TIMEZONE = re.compile(r"^\s*timezone:\s*\"([^\"]+)\"", re.MULTILINE)
_SCHEDULE = re.compile(r"\bschedule:\s*\[([^\]]*)\]")
_QUOTED = re.compile(r"\"([^\"]*)\"")


class WindowError(Exception):
    """The configuration can't be checked."""


def _expand(field: str, low: int, high: int, what: str) -> frozenset[int]:
    values: set[int] = set()
    for part in field.split(","):
        base, slash, step_text = part.partition("/")
        try:
            step = int(step_text) if slash else 1
            if base == "*":
                first, last = low, high
            elif "-" in base:
                first, last = (int(x) for x in base.split("-"))
            else:
                first = int(base)
                last = high if slash else first
        except ValueError:
            raise WindowError(f"unsupported {what} field {field!r}") from None
        if step < 1 or not low <= first <= last <= high:
            raise WindowError(f"{what} field {field!r} is out of range {low}-{high}")
        values.update(range(first, last + 1, step))
    return frozenset(values)


@dataclass(frozen=True)
class Schedule:
    expression: str
    hours: frozenset[int]
    days_of_month: frozenset[int]
    months: frozenset[int]
    days_of_week: frozenset[int]  # 0 = Sunday
    dom_restricted: bool
    dow_restricted: bool

    @classmethod
    def parse(cls, expression: str) -> Schedule:
        fields = expression.split()
        if len(fields) != 5:
            raise WindowError(f"schedule {expression!r} must have 5 cron fields")
        minute, hour, dom, month, dow = fields
        if minute != "*":
            raise WindowError(f"schedule {expression!r}: Renovate's cron has no minute granularity, minutes must be '*'")
        return cls(
            expression,
            _expand(hour, 0, 23, "hour"),
            _expand(dom, 1, 31, "day-of-month"),
            _expand(month, 1, 12, "month"),
            frozenset(d % 7 for d in _expand(dow, 0, 7, "day-of-week")),
            dom != "*",
            dow != "*",
        )

    def has_window_on(self, moment: datetime) -> bool:
        """Does the schedule allow any hour on this local date?"""
        if moment.month not in self.months:
            return False
        dom_ok = moment.day in self.days_of_month
        dow_ok = (moment.weekday() + 1) % 7 in self.days_of_week
        # Standard cron: with both fields restricted either may match.
        return (dom_ok or dow_ok) if self.dom_restricted and self.dow_restricted else (dom_ok and dow_ok)

    def compliant(self, moment: datetime) -> bool:
        return not self.has_window_on(moment) or moment.hour in self.hours


def load_config(root: Path) -> tuple[str, list[Schedule]]:
    """(timezone, schedules) from renovate.json5; every `schedule:` array counts."""
    path = root / RENOVATE_CONFIG
    try:
        text = path.read_text()
    except OSError as exc:
        raise WindowError(f"can't read {RENOVATE_CONFIG}: {exc}") from exc
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//"))
    expressions = list(dict.fromkeys(e for body in _SCHEDULE.findall(code) for e in _QUOTED.findall(body)))
    if not expressions:
        raise WindowError(f"no `schedule:` found in {RENOVATE_CONFIG}; nothing to check")
    zone = _TIMEZONE.search(code)
    if not zone:
        raise WindowError(f"{RENOVATE_CONFIG} sets a schedule but no `timezone:`")
    return zone.group(1), [Schedule.parse(e) for e in expressions]


def check(root: Path, started_epoch: int) -> list[str]:
    """One message per schedule the run started outside of."""
    zone_name, schedules = load_config(root)
    try:
        started = datetime.fromtimestamp(started_epoch, ZoneInfo(zone_name))
    except ZoneInfoNotFoundError:
        raise WindowError(f"unknown timezone {zone_name!r} in {RENOVATE_CONFIG}") from None
    return [
        f"Run started {started:%a %Y-%m-%d %H:%M} ({zone_name}), outside the PR-creation window {schedule.expression!r} — no new PRs opened this cycle."
        for schedule in schedules
        if not schedule.compliant(started)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("started_epoch", type=int)
    args = parser.parse_args(argv)
    try:
        problems = check(REPO_ROOT, args.started_epoch)
    except WindowError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    for problem in problems:
        print(f"::error::{problem}")
    if not problems:
        print("Run started inside the PR-creation window, or on a day with none.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
