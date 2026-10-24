"""Writing the progress log: read what is new on `main`, update the files, record where reading stopped.

    python -m progress_log --repo PATH --out DIR [--full] [--head REV] [--repo-url URL]

`DIR` is a checkout of the `progress-log` branch. A run reads only the changes
after `state.json`'s `last_sha`, and rewrites only the weeks and months those
changes fall in. A recorded commit that is no longer an ancestor of the head
(history was rewritten) is ignored: the whole log is rebuilt from `main`, and
the notes written under each week's marker are kept.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from progress_log import history, render

DEFAULT_REPO_URL = "https://github.com/wenenhoe/homelab"


def _load_weeks(out: Path) -> dict[str, dict]:
    return {path.stem: json.loads(path.read_text()) for path in sorted((out / "data").glob("*.json"))}


def _read_state(out: Path) -> dict:
    path = out / "state.json"
    return json.loads(path.read_text()) if path.exists() else {}


def generate(repo: Path, out: Path, *, head_rev: str = "HEAD", full: bool = False, repo_url: str = DEFAULT_REPO_URL) -> str:
    """Bring `out` up to date with `head_rev`; returns a one-line account of what was read."""
    for directory in ("data", "weeks", "months"):
        (out / directory).mkdir(parents=True, exist_ok=True)
    head = history.git(repo, "rev-parse", head_rev).strip()
    state = _read_state(out)
    last = state.get("last_sha")
    resume = bool(last) and not full and history.is_ancestor(repo, last, head)
    if not resume:
        last = None
        for path in (out / "data").glob("*.json"):
            path.unlink()
    units = history.parse_units(repo, [f"{last}..{head}"] if last else [head])

    weeks = _load_weeks(out)
    touched: set[str] = set()
    for unit in units:
        key = render.week_key(datetime.fromisoformat(unit["date"]))
        week = weeks.setdefault(key, {"week": key, "units": []})
        if all(known["sha"] != unit["sha"] for known in week["units"]):
            week["units"].append(unit)
        touched.add(key)
    for key in touched:
        weeks[key]["units"].sort(key=lambda unit: (unit["date"], unit["sha"]))
        (out / "data" / f"{key}.json").write_text(json.dumps(weeks[key], indent=1) + "\n")

    current = max(weeks) if weeks else None
    # The week that was in progress last run loses its marker when a newer week exists.
    to_render = touched | {key for key in (current, state.get("current_week")) if key in weeks}
    for key in sorted(to_render):
        render.render_week(key, weeks[key]["units"], repo_url, current, out)
    months = sorted({unit["date"][:7] for key in touched for unit in weeks[key]["units"]})
    for month in months:
        render.render_month(month, weeks, out)
    render.render_index(weeks, head, out)
    (out / "state.json").write_text(json.dumps({"last_sha": head, "current_week": current}, indent=1) + "\n")
    how = f"incremental from {last[:7]}" if last else "full"
    return f"read {len(units)} new changes ({how}); rewrote weeks {sorted(touched)} months {months}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="progress_log", description="Write the weekly and monthly progress log from a repository's history.")
    parser.add_argument("--repo", type=Path, required=True, help="the repository to read")
    parser.add_argument("--out", type=Path, required=True, help="the directory the log is written to (a checkout of the progress-log branch)")
    parser.add_argument("--full", action="store_true", help="rebuild everything instead of resuming from state.json")
    parser.add_argument("--head", default="HEAD", help="the revision to read up to (default HEAD)")
    parser.add_argument("--repo-url", default=DEFAULT_REPO_URL, help="the repository's web URL, for pull request links")
    args = parser.parse_args(argv)
    print(generate(args.repo, args.out, head_rev=args.head, full=args.full, repo_url=args.repo_url))
    return 0
