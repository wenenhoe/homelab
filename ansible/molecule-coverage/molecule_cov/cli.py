"""molecule-coverage CLI.

Run from this directory (ansible/molecule-coverage/):

    python3 -m molecule_cov.cli inventory ../roles/caddy --coverage-dir .data
    python3 -m molecule_cov.cli report --coverage-dir .data --role caddy \
        --thresholds-file thresholds.yaml

See ../README.md for the full command reference. aggregate.py has no
subcommand of its own - compute_coverage() is used as a library, by
`report` above.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

from molecule_cov.aggregate import compute_coverage
from molecule_cov.inventory import scan_role
from molecule_cov.report import (
    discover_roles,
    failing_roles_under,
    missing_and_failing_against_thresholds,
    print_role_detail,
    print_summary,
)


def _inventory(args: argparse.Namespace) -> int:
    role_dir = args.role_dir.resolve()
    if not role_dir.is_dir():
        print(f"error: {role_dir} is not a directory", file=sys.stderr)
        return 1

    inventory = scan_role(role_dir)
    role_name = role_dir.name

    if args.stdout:
        print(json.dumps(inventory, indent=2))
        return 0

    out_path = args.coverage_dir / role_name / "_inventory.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(inventory)} task(s) to {out_path}")
    return 0


def _report(args: argparse.Namespace) -> int:
    coverage_dir = args.coverage_dir.resolve()

    if args.role:
        role_dir = coverage_dir / args.role
        if not role_dir.is_dir():
            print(f"error: no data for role '{args.role}' under {coverage_dir}", file=sys.stderr)
            return 1
        try:
            report = compute_coverage(role_dir)
        except FileNotFoundError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print_role_detail(report)
        reports = [report]
    else:
        role_dirs = discover_roles(coverage_dir)
        if not role_dirs:
            print(f"no roles with coverage data found under {coverage_dir}", file=sys.stderr)
            return 1
        reports = [compute_coverage(d) for d in role_dirs]
        print_summary(reports)
        if args.show_all:
            for report in reports:
                print()
                print("=" * 40)
                print()
                print_role_detail(report)

    if args.fail_under is not None:
        failing = failing_roles_under(reports, args.fail_under)
        if failing:
            print(f"\nFAIL: below {args.fail_under}% coverage: {', '.join(failing)}", file=sys.stderr)
            return 1

    if args.thresholds_file is not None:
        thresholds = yaml.safe_load(args.thresholds_file.read_text(encoding="utf-8")) or {}
        missing, failing = missing_and_failing_against_thresholds(reports, thresholds)
        if missing:
            print(
                f"\nERROR: no threshold entry for: {', '.join(missing)} "
                f"in {args.thresholds_file} - add one before this can gate.",
                file=sys.stderr,
            )
            return 2
        if failing:
            print(f"\nFAIL: below its threshold: {', '.join(failing)}", file=sys.stderr)
            return 1

    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="molecule_cov.cli", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory_parser = subparsers.add_parser(
        "inventory", help="Scan a role's tasks/ into a static inventory JSON file."
    )
    inventory_parser.add_argument("role_dir", type=Path, help="Path to a role directory, e.g. ../roles/caddy")
    inventory_parser.add_argument(
        "--coverage-dir",
        type=Path,
        default=Path(os.environ.get("MOLECULE_COVERAGE_DIR", "./.molecule-coverage-data")),
        help="Directory to write <role>/_inventory.json into (same root the callback plugin writes JSONL under).",
    )
    inventory_parser.add_argument(
        "--stdout", action="store_true", help="Print the inventory to stdout instead of writing a file."
    )
    inventory_parser.set_defaults(func=_inventory)

    report_parser = subparsers.add_parser("report", help="Print a coverage report from previously-collected data.")
    report_parser.add_argument(
        "--coverage-dir",
        type=Path,
        # Same MOLECULE_COVERAGE_DIR fallback as the inventory subcommand
        # above - the old top-level report.py's default didn't honor this
        # env var (inventory.py's did), an inherited inconsistency fixed
        # here rather than carried forward.
        default=Path(os.environ.get("MOLECULE_COVERAGE_DIR", "./.molecule-coverage-data")),
        help="Directory containing <role>/_inventory.json + <role>/<scenario>.jsonl for each role",
    )
    role_selection = report_parser.add_mutually_exclusive_group()
    role_selection.add_argument(
        "--role", help="Show a per-task drill-down for this one role instead of the summary table"
    )
    role_selection.add_argument(
        "--show-all",
        action="store_true",
        help="Print the summary table, then every role's per-task drill-down, in one go",
    )
    threshold_group = report_parser.add_mutually_exclusive_group()
    threshold_group.add_argument(
        "--fail-under",
        type=float,
        default=None,
        help="Exit 1 if any reported role's aggregate coverage_pct is below this single threshold",
    )
    threshold_group.add_argument(
        "--thresholds-file",
        type=Path,
        default=None,
        help="YAML file of {role: floor}. Exit 1 if any reported role is below its floor, "
        "or 2 if a reported role has no entry (see thresholds.yaml)",
    )
    report_parser.set_defaults(func=_report)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
