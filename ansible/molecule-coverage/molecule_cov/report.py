"""molecule-coverage: report formatting

Human-readable view on top of aggregate.py's JSON: a summary table across
all roles found in a coverage directory, or a per-task drill-down for one
role. Stdlib only - no tabulate/rich dependency, to keep this easy to run
anywhere.

The two threshold-checking functions (`failing_roles_under`,
`missing_and_failing_against_thresholds`) take an already-computed list of
reports and an already-parsed thresholds mapping - no file I/O - so they're
directly unit-testable without a coverage-dir fixture on disk. cli.py owns
reading `--thresholds-file` and turning these into exit codes.
"""
from __future__ import annotations

from pathlib import Path


def _loop_summary(loop_coverage: dict | None) -> str:
    if loop_coverage is None:
        return "-"
    observed = loop_coverage["items_observed_count"]
    skipped_only = loop_coverage["items_skipped_only_count"]
    if observed == 0 and skipped_only == 0:
        # Either the loop came back empty every time it was observed, or
        # the task itself was never observed at all (has_loop tasks can
        # still be never_observed like any other task).
        return "empty loop" if loop_coverage["observed_empty_loop"] else "no items observed"
    if skipped_only > 0:
        # The real point of this column: task-level status alone would
        # say "covered" here even though some items never ran.
        examples = ", ".join(loop_coverage["items_skipped_only"][:3])
        more = "..." if loop_coverage["items_skipped_only_truncated"] or skipped_only > 3 else ""
        return f"{observed} ok, {skipped_only} never ran ({examples}{more})"
    return f"{observed} item(s) ok"


def _has_partial_loop_gap(task: dict) -> bool:
    lc = task.get("loop_coverage")
    return bool(lc and lc["items_skipped_only_count"] > 0)


def _branch_summary(branch_coverage: dict | None) -> str:
    if branch_coverage is None:
        return "-"
    status = branch_coverage["branch_status"]
    return {
        "both_branches": "both ok",
        "true_only": "never negated",
        "false_only": "never satisfied",
        "never_observed": "no data",
    }[status]


def _has_untested_false_branch(task: dict) -> bool:
    bc = task.get("branch_coverage")
    return bool(bc and bc["branch_status"] == "true_only")


def discover_roles(coverage_dir: Path) -> list[Path]:
    if not coverage_dir.is_dir():
        return []
    return sorted(
        p.parent for p in coverage_dir.glob("*/_inventory.json") if p.is_file()
    )


def _fmt_pct(pct: float | None) -> str:
    return "n/a" if pct is None else f"{pct:5.1f}%"


def print_summary(reports: list[dict]) -> None:
    headers = ["Role", "Scenarios", "Tasks", "Covered", "Skip-only", "Never-obs", "Coverage"]
    rows = []
    for r in reports:
        s = r["summary"]
        rows.append(
            [
                r["role"],
                str(len(r["scenarios"])),
                str(s["total"]),
                str(s["covered"]),
                str(s["skipped_only"]),
                str(s["never_observed"]),
                _fmt_pct(s["coverage_pct"]),
            ]
        )

    total = sum(r["summary"]["total"] for r in reports)
    covered = sum(r["summary"]["covered"] for r in reports)
    skipped_only = sum(r["summary"]["skipped_only"] for r in reports)
    never_observed = sum(r["summary"]["never_observed"] for r in reports)
    overall_pct = round(100 * covered / total, 1) if total else None
    rows.append(
        [
            "TOTAL",
            "",
            str(total),
            str(covered),
            str(skipped_only),
            str(never_observed),
            _fmt_pct(overall_pct),
        ]
    )

    widths = [
        max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(len(headers))
    ]
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print("-" * len(line))
    for i, row in enumerate(rows):
        if i == len(rows) - 1:
            print("-" * len(line))
        print("  ".join(cell.ljust(widths[j]) for j, cell in enumerate(row)))


def print_role_detail(report: dict) -> None:
    print(f"role: {report['role']}  (scenarios: {', '.join(report['scenarios']) or 'none'})")
    print()

    # Sorted in source order (file alphabetically, then line in sequence)
    # so the table reads the same way as the actual code, rather than
    # jumbling tasks by status - the Status/Loop/Branch columns are still
    # right there per row, and problem tasks get called out again
    # explicitly in the summary notes below regardless of where they sort.
    tasks = sorted(
        report["tasks"],
        key=lambda t: (t["task_file"] or "", t["task_line"] or 0),
    )

    headers = ["Status", "Task", "Location", "Loop", "Branch", "Per-scenario"]
    rows = []
    for t in tasks:
        loc = f"{Path(t['task_file']).name if t['task_file'] else '?'}:{t['task_line'] or '?'}"
        per_scenario = ", ".join(f"{sc}={st}" for sc, st in sorted(t["per_scenario"].items()))
        rows.append(
            [
                t["aggregate_status"],
                (t["task_name"] or "")[:60],
                loc,
                _loop_summary(t.get("loop_coverage")),
                _branch_summary(t.get("branch_coverage")),
                per_scenario or "(no scenarios run)",
            ]
        )

    widths = [max(len(headers[i]), *(len(row[i]) for row in rows)) if rows else len(headers[i]) for i in range(len(headers))]
    widths = [min(w, 60) for w in widths]
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print("-" * len(line))
    for row in rows:
        print("  ".join(str(cell).ljust(widths[j]) for j, cell in enumerate(row)))

    print()
    s = report["summary"]
    print(
        f"summary: {s['covered']}/{s['total']} covered "
        f"({_fmt_pct(s['coverage_pct']).strip()}), "
        f"{s['skipped_only']} skipped-only, {s['never_observed']} never observed"
    )
    partial_loop_tasks = [t for t in report["tasks"] if _has_partial_loop_gap(t)]
    if partial_loop_tasks:
        print(
            f"note: {len(partial_loop_tasks)} looped task(s) show 'covered' above "
            f"but have items that never ran - see the Loop column"
        )
    untested_false = [t for t in report["tasks"] if _has_untested_false_branch(t)]
    if untested_false:
        print(
            f"note: {len(untested_false)} task(s) show 'covered' above but their "
            f"when: has never been observed false - i.e. its skip path is untested:"
        )
        for t in untested_false:
            loc = f"{Path(t['task_file']).name if t['task_file'] else '?'}:{t['task_line'] or '?'}"
            clauses = " and ".join(t["when"] or [])
            print(f"  - {t['task_name']} ({loc}): when: {clauses}")


def failing_roles_under(reports: list[dict], threshold: float) -> list[str]:
    """Roles whose aggregate coverage_pct is below a single global floor.
    A role with coverage_pct None (no tasks at all) never fails - there's
    nothing to be below the threshold."""
    return [
        r["role"]
        for r in reports
        if r["summary"]["coverage_pct"] is not None and r["summary"]["coverage_pct"] < threshold
    ]


def missing_and_failing_against_thresholds(
    reports: list[dict], thresholds: dict[str, float]
) -> tuple[list[str], list[str]]:
    """(missing, failing) against a per-role {role: floor} mapping. A role
    with data but no threshold entry is reported as missing rather than
    silently passing - a new role should get a deliberate floor, not an
    accidental free ride. Failing is only evaluated for roles that do have
    an entry."""
    missing = [r["role"] for r in reports if r["role"] not in thresholds]
    failing = [
        r["role"]
        for r in reports
        if r["role"] in thresholds
        and r["summary"]["coverage_pct"] is not None
        and r["summary"]["coverage_pct"] < thresholds[r["role"]]
    ]
    return missing, failing
