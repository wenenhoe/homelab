"""Turning a period's changes into markdown: a week file, a month file and the index."""

from __future__ import annotations

import html
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from progress_log.classify import DECISIONS, DEPENDENCY_UPDATES, PROJECT_PREFIX

NOTES_MARK = "<!-- notes: hand-written below this line, kept on regeneration -->"
LEGEND = (
    "_Counts are merged PRs (direct commits before the PR workflow). "
    "**Code** = changed code, config, tests or deployment · "
    "**Docs** = docs and decisions only · "
    "**Project-doc edits** = changed only project docs._"
)
TITLE_WIDTH = 80


def week_key(moment: datetime) -> str:
    year, week, _ = moment.isocalendar()
    return f"{year}-W{week:02d}"


def week_bounds(key: str) -> tuple[date, date]:
    year, week = key.split("-W")
    start = date.fromisocalendar(int(year), int(week), 1)
    return start, start + timedelta(days=6)


def _day(iso: str) -> str:
    moment = datetime.fromisoformat(iso)
    return f"{moment.day} {moment.strftime('%b')}"


def _escape(text: str) -> str:
    return html.escape(text, quote=False)


def _truncate(text: str, width: int = TITLE_WIDTH) -> str:
    return text if len(text) <= width else text[: width - 1].rstrip() + "…"


def _details(summary: str, body: list[str]) -> list[str]:
    return ["<details>", f"<summary>{summary}</summary>", "", *body, "", "</details>", ""]


def _ref(unit: dict, url: str) -> str:
    return f"[#{unit['pr']}]({url}/pull/{unit['pr']})" if unit["pr"] else f"`{unit['sha'][:7]}`"


def _names(items: list[str], cap: int = 6) -> str:
    items = list(dict.fromkeys(items))
    text = ", ".join(items[:cap])
    return text + (f" +{len(items) - cap} more" if len(items) > cap else "")


def counts(units: list[dict]) -> tuple[int, int, int, int]:
    """(code, docs, project-doc edits, dependency updates)."""
    tally = Counter(unit["cat"] for unit in units)
    return tally["built"], tally["planned"], tally["scope"], tally["dep"]


def headline(units: list[dict]) -> str:
    code, docs, scope, deps = counts(units)
    noun = "PRs" if all(unit["kind"] == "pr" for unit in units if unit["cat"] != "dep") else "changes"
    text = f"**{code + docs + scope} {noun}** — {code} code · {docs} docs · {scope} project-doc edits"
    return text + (f" · plus {deps} dependency updates" if deps else "")


def summarise(units: list[dict]) -> dict:
    """The milestones in a set of changes, with scoping churn netted out."""
    projects = [(event[1], event[2]) for unit in units for event in unit["events"] if event[0] == "project"]
    opened = {slug: what for slug, what in projects if what.startswith("opened")}
    closed = [slug for slug, what in projects if what == "closed"]
    # Opened as not-started and removed in the same span is re-scoping, not progress.
    churn = {slug for slug in closed if opened.get(slug) == "opened (not-started)"}
    closed = [slug for slug in closed if slug not in churn]
    gone = set(closed) | churn
    building = [slug for slug, what in projects if (what.endswith("→ building") or what == "opened (building)") and slug not in gone]
    derisking = [slug for slug, what in projects if (what.endswith("→ de-risking") or what == "opened (de-risking)") and slug not in gone]
    building = list(dict.fromkeys(building))
    derisking = [slug for slug in dict.fromkeys(derisking) if slug not in building]
    scoped = [slug for slug, what in opened.items() if what == "opened (not-started)" and slug not in gone | set(building) | set(derisking)]
    decisions = [(re.match(r"ADR (\d{4})", name).group(1), what) for unit in units for kind, name, what in unit["events"] if kind == "adr"]
    components = [(name, what) for unit in units for kind, name, what in unit["events"] if kind == "component"]
    accepted = list(dict.fromkeys(n for n, what in decisions if what.endswith("→ accepted") or what == "added (accepted)"))
    approved = [n for n in dict.fromkeys(n for n, what in decisions if what.endswith("→ approved") or what == "added (approved)") if n not in accepted]
    return {
        "closed": list(dict.fromkeys(closed)),
        "building": building,
        "derisk": derisking,
        "scoped": list(dict.fromkeys(scoped)),
        "adr_accepted": accepted,
        "adr_approved": approved,
        "adr_new": len({n for n, what in decisions if what.startswith("added")}),
        "comp_added": [n for n, what in components if what == "added"],
        "comp_removed": [n for n, what in components if what == "removed"],
        "churn": len(churn),
    }


def highlights(units: list[dict]) -> list[str]:
    s = summarise(units)
    out = []
    if s["closed"]:
        out.append(f"- **Closed:** {_names(s['closed'])}")
    if s["building"]:
        out.append(f"- **Started building:** {_names(s['building'])}")
    if s["derisk"]:
        out.append(f"- **Started de-risking:** {_names(s['derisk'])}")
    if s["scoped"]:
        out.append(f"- **Scoped, not started:** {len(s['scoped'])} new — {_names(s['scoped'], 4)}")
    decisions = []
    if s["adr_accepted"]:
        decisions.append(f"accepted {_names(s['adr_accepted'])}")
    if s["adr_approved"]:
        decisions.append(f"approved {_names(s['adr_approved'])}")
    if s["adr_new"]:
        decisions.append(f"{s['adr_new']} new")
    if decisions:
        out.append(f"- **Decisions:** {' · '.join(decisions)}")
    components = [f"+ {c}" for c in s["comp_added"]] + [f"- {c}" for c in s["comp_removed"]]
    if components:
        out.append(f"- **Components:** {_names(components)}")
    return out or ["_No project, decision or component milestones._"]


def _themes(units: list[dict], cap: int) -> tuple[list[str], str]:
    tally: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    column = {"built": 0, "planned": 1, "scope": 2}
    for unit in units:
        if unit["cat"] != "dep":
            tally[unit["group"]][column[unit["cat"]]] += 1
    rows = sorted(tally.items(), key=lambda row: (-row[1][0], -(row[1][1] + row[1][2]), row[0]))

    def cell(n: int) -> str | int:
        return n or ""

    lines = ["| Area / theme | Code | Docs | Project-doc edits |", "| :--- | ---: | ---: | ---: |"]
    lines += [f"| {_escape(label)} | {cell(v[0])} | {cell(v[1])} | {cell(v[2])} |" for label, v in rows[:cap]]
    rest = rows[cap:]
    if rest:
        total = [sum(row[1][i] for row in rest) for i in range(3)]
        lines.append(f"| {len(rest)} other themes | {cell(total[0])} | {cell(total[1])} | {cell(total[2])} |")
    return lines, (rows[0][0] if rows else "—")


def _group_order(groups: dict[str, list[dict]]) -> list[tuple[str, list[dict]]]:
    def rank(entry: tuple[str, list[dict]]) -> tuple[int, int, str]:
        label, units = entry
        tier = 0 if label.startswith(PROJECT_PREFIX) else 1 if label == DECISIONS else 3 if label == DEPENDENCY_UPDATES else 2
        return (tier, -len(units), label)

    return sorted(groups.items(), key=rank)


def _full_list(units: list[dict], url: str) -> list[str]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for unit in units:
        groups[unit["group"]].append(unit)
    body: list[str] = []
    for label, members in _group_order(groups):
        if label == DEPENDENCY_UPDATES:
            continue
        members.sort(key=lambda unit: unit["date"])
        body += [f"**{_escape(label)}**", ""]
        body += [f"- {_ref(unit, url)} {_escape(_truncate(unit['title']))}" for unit in members if unit["cat"] != "scope"]
        scope = [unit for unit in members if unit["cat"] == "scope"]
        if scope:
            body.append("- _Project-doc edits:_ " + " ".join(_ref(unit, url) for unit in scope))
        body.append("")
    listed = sum(1 for unit in units if unit["cat"] != "dep")
    deps = len(units) - listed
    if deps:
        body.append(f"_{deps} dependency updates (Renovate) not listed._")
    return _details(f"All {listed} changes", body)


def _event_log(units: list[dict]) -> list[str]:
    rows = [
        f"- {_day(unit['date'])} · {name}: {what}" if kind == "adr" else f"- {_day(unit['date'])} · **{name}** {what}"
        for unit in units
        for kind, name, what in unit["events"]
        if kind in ("project", "adr")
    ]
    return _details(f"Project and decision log ({len(rows)})", rows) if rows else []


def read_notes(path: Path) -> str:
    """What was written under the notes marker of an existing file, or nothing."""
    if path.exists():
        text = path.read_text()
        if NOTES_MARK in text:
            return text.split(NOTES_MARK, 1)[1].lstrip("\n")
    return ""


def render_week(key: str, units: list[dict], url: str, current: str | None, out: Path) -> None:
    start, end = week_bounds(key)
    path = out / "weeks" / f"{key}.md"
    status = " *(in progress)*" if key == current else ""
    table, _ = _themes(units, 8)
    lines = [
        f"# {key} · {start.day} {start.strftime('%b')} to {end.day} {end.strftime('%b %Y')}{status}", "",
        headline(units), "", LEGEND, "",
        "## Highlights", "", *highlights(units), "",
        "## Themes", "", *table, "",
        *_full_list(units, url), *_event_log(units),
        NOTES_MARK, read_notes(path) or "_Notes:_\n",
    ]  # fmt: skip
    path.write_text("\n".join(lines).rstrip() + "\n")


def render_month(key: str, weeks: dict[str, dict], out: Path) -> None:
    units = sorted((unit for week in weeks.values() for unit in week["units"] if unit["date"][:7] == key), key=lambda unit: unit["date"])
    year, month = map(int, key.split("-"))
    table, _ = _themes(units, 12)
    by_week: dict[str, list[dict]] = defaultdict(list)
    for unit in units:
        by_week[week_key(datetime.fromisoformat(unit["date"]))].append(unit)
    rows = ["| Week | Code | Docs | Project-doc edits | Dep. updates | Busiest theme |", "| :--- | ---: | ---: | ---: | ---: | :--- |"]
    for week in sorted(by_week):
        code, docs, scope, deps = counts(by_week[week])
        rows.append(f"| [{week}](../weeks/{week}.md) | {code} | {docs} | {scope} | {deps} | {_escape(_themes(by_week[week], 1)[1])} |")
    lines = [
        f"# {date(year, month, 1).strftime('%B %Y')}", "", headline(units), "", LEGEND, "",
        "## Highlights", "", *highlights(units), "",
        "## Themes", "", *table, "",
        "## Weeks", "", *rows,
    ]  # fmt: skip
    (out / "months" / f"{key}.md").write_text("\n".join(lines).rstrip() + "\n")


def render_index(weeks: dict[str, dict], head: str, out: Path) -> None:
    lines = [
        "# Homelab progress log", "",
        f"Generated from `main` up to `{head[:7]}`. Weeks run Monday to Sunday (UTC+8). "
        "Past weeks are frozen once written; add your own notes under the marker in a week file and they survive regeneration.",
        "", LEGEND, "",
        "## Recent weeks", "",
        "| Week | Code | Docs | Project-doc edits | Dep. updates | Projects closed |",
        "| :--- | ---: | ---: | ---: | ---: | ---: |",
    ]  # fmt: skip
    for key in reversed(sorted(weeks)[-8:]):
        units = weeks[key]["units"]
        code, docs, scope, deps = counts(units)
        lines.append(f"| [{key}](weeks/{key}.md) | {code} | {docs} | {scope} | {deps} | {len(summarise(units)['closed'])} |")
    months = sorted({unit["date"][:7] for week in weeks.values() for unit in week["units"]}, reverse=True)
    lines += ["", "## Months", "", *(f"- [{month}](months/{month}.md)" for month in months)]
    (out / "README.md").write_text("\n".join(lines) + "\n")
