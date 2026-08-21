#!/usr/bin/env python3
"""Checks a handful of docs/README sections against the files they
describe, so an added/removed role, playbook, scenario, CI job, or
cross-doc link can't silently drift out of sync with what documents it.

Narrow presence/shape checks only, deliberately not content-equality —
see each check's docstring for what it does and doesn't catch, and
docs/ci.md#docs-drift-check for the summary.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
errors: list[str] = []

ANCHOR_SCAN_EXTS = {".md", ".yml", ".yaml", ".py"}
ANCHOR_SCAN_EXTRA_NAMES = {".trivyignore"}
ANCHOR_SCAN_EXCLUDE_DIRS = {".git", "node_modules", ".venv"}

CROSS_FILE_ANCHOR_RE = re.compile(r"([\w./-]+\.md)#([\w-]+)")
SAME_FILE_ANCHOR_RE = re.compile(r"\]\(#([\w-]+)\)")


def fail(msg: str) -> None:
    errors.append(msg)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def check_readme() -> None:
    """Every docs/*.md file is linked somewhere in README.md; every
    docs/*.md link in README.md resolves to a real file. Substring
    matching, not table parsing — cheap, and false positives (a name
    coincidentally appearing elsewhere) are the safe failure mode here,
    not false negatives.
    """
    readme = read(ROOT / "README.md")

    for doc in sorted((ROOT / "docs").glob("*.md")):
        if f"docs/{doc.name}" not in readme:
            fail(f"README: docs/{doc.name} exists but isn't linked anywhere in README.md")

    for link in re.findall(r"docs/[\w-]+\.md", readme):
        if not (ROOT / link).is_file():
            fail(f"README: links {link}, which doesn't exist")


def check_ansible_reference() -> None:
    """docs/ansible.md's Playbooks table lists every ansible/playbooks/*.yaml
    file; its Roles table lists every ansible/roles/*/ directory. Same
    presence-only matching as check_readme() used to do against README's
    tree, before that moved here.
    """
    doc = read(ROOT / "docs/ansible.md")

    pb_section = re.search(r"## Playbooks\n\n(.*?)\n\n", doc, re.DOTALL)
    if not pb_section:
        fail("ansible.md: couldn't find the ## Playbooks table")
    else:
        documented = set(re.findall(r"^\| `playbooks/([\w.-]+)`", pb_section.group(1), re.MULTILINE))
        actual = {pb.name for pb in (ROOT / "ansible/playbooks").glob("*.yaml")}
        for pb in sorted(actual - documented):
            fail(f"ansible.md Playbooks table: missing a row for ansible/playbooks/{pb}")
        for pb in sorted(documented - actual):
            fail(f"ansible.md Playbooks table: documents playbooks/{pb}, which doesn't exist")

    roles_section = re.search(r"## Roles\n\n(.*?)\n\n", doc, re.DOTALL)
    if not roles_section:
        fail("ansible.md: couldn't find the ## Roles table")
    else:
        documented = set(re.findall(r"^\| `([\w]+)`", roles_section.group(1), re.MULTILINE))
        actual = {d.name for d in (ROOT / "ansible/roles").iterdir() if d.is_dir()}
        for role in sorted(actual - documented):
            fail(f"ansible.md Roles table: missing a row for ansible/roles/{role}/")
        for role in sorted(documented - actual):
            fail(f"ansible.md Roles table: documents role '{role}', which doesn't exist")


def check_molecule_matrix() -> None:
    """docs/molecule-testing.md's Scenario matrix table, role-for-role
    and scenario-for-scenario, against the real
    ansible/roles/*/molecule/*/ directories.
    """
    lines = read(ROOT / "docs/molecule-testing.md").splitlines()
    start = next(i for i, l in enumerate(lines) if l.strip() == "## Scenario matrix")
    table_lines: list[str] = []
    for line in lines[start:]:
        if line.startswith("|"):
            table_lines.append(line)
        elif table_lines:
            break
    rows = table_lines[2:]  # drop header + separator row

    documented: dict[str, set[str]] = {}
    current_role: str | None = None
    for row in rows:
        cells = [c.strip() for c in row.strip("|").split("|")]
        role_cell, scenario_cell = cells[0].strip("`"), cells[1].strip("`")
        current_role = role_cell or current_role
        if current_role is None:
            continue
        bucket = documented.setdefault(current_role, set())
        if scenario_cell == "*(none)*":
            bucket.add("__none__")
        elif scenario_cell:
            bucket.add(scenario_cell)

    # Shared test scaffolding, not a role under test — documented in its
    # own "## `molecule_helpers`" section instead of the matrix.
    excluded_roles = {"molecule_helpers"}

    for role_dir in sorted((ROOT / "ansible/roles").iterdir()):
        if not role_dir.is_dir() or role_dir.name in excluded_roles:
            continue
        role = role_dir.name
        molecule_dir = role_dir / "molecule"
        if molecule_dir.is_dir():
            actual = {p.name for p in molecule_dir.iterdir() if p.is_dir()}
        else:
            actual = {"__none__"}

        if role not in documented:
            fail(f"molecule-testing.md: role '{role}' has no Scenario matrix row at all")
            continue

        for scenario in sorted(actual - documented[role]):
            label = "(no molecule dir)" if scenario == "__none__" else scenario
            fail(f"molecule-testing.md: {role}'s scenario '{label}' isn't in the Scenario matrix table")
        for scenario in sorted(documented[role] - actual):
            label = "*(none)*" if scenario == "__none__" else scenario
            fail(f"molecule-testing.md: Scenario matrix lists {role}/{label}, which doesn't exist")


def check_deploy_flow() -> None:
    """Count + sequence only, not title text: deploy.yaml's play names
    and deployment-flow.md's headings are allowed to word the same play
    differently (e.g. a shortened heading), that's not drift worth
    flagging. What matters is a play being added, removed, or reordered
    without the docs' numbering following it.
    """
    play_names = re.findall(r"^- name:\s*(.+)$", read(ROOT / "ansible/playbooks/deploy.yaml"), re.MULTILINE)
    heading_nums = [int(n) for n in re.findall(r"^## Play (\d+)", read(ROOT / "docs/deployment-flow.md"), re.MULTILINE)]

    if len(heading_nums) != len(play_names):
        fail(
            f"deployment-flow.md: {len(heading_nums)} 'Play N' headings vs "
            f"{len(play_names)} plays in deploy.yaml — one was added/removed without the other"
        )
    elif heading_nums != list(range(len(heading_nums))):
        fail(f"deployment-flow.md: 'Play N' headings aren't sequential from 0: {heading_nums}")


def check_ci_jobs_table() -> None:
    """docs/ci.md's Jobs table against pr-checks.yml's actual job ids."""
    workflow = yaml.safe_load(read(ROOT / ".github/workflows/pr-checks.yml"))
    job_ids = set(workflow["jobs"].keys())

    section = re.search(r"## Jobs\n\n(.*?)\n\n", read(ROOT / "docs/ci.md"), re.DOTALL)
    if not section:
        fail("ci.md: couldn't find the ## Jobs table")
        return
    documented = set(re.findall(r"^\| `([\w-]+)`", section.group(1), re.MULTILINE))

    # detect-changes is internal plumbing (feeds other jobs' outputs, not
    # itself a check); trivy-scan is documented in security-scanning.md
    # instead of a Jobs table row.
    allowed_undocumented = {"detect-changes", "trivy-scan"}

    for job in sorted(job_ids - documented - allowed_undocumented):
        fail(f"ci.md Jobs table: missing a row for pr-checks.yml's '{job}' job")
    for job in sorted(documented - job_ids):
        fail(f"ci.md Jobs table: documents '{job}', which isn't a job in pr-checks.yml")


def _slugify(heading: str) -> str:
    """Approximates GitHub's heading-to-anchor algorithm: lowercase,
    drop anything that isn't a word char/space/hyphen, then turn every
    individual whitespace char into its own hyphen (consecutive spaces
    stay separate hyphens, they don't collapse into one).
    """
    text = heading.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    return re.sub(r"\s", "-", text)


def _heading_slugs(path: Path) -> set[str]:
    slugs: set[str] = set()
    seen: dict[str, int] = {}
    for line in read(path).splitlines():
        m = re.match(r"^#{1,6}\s+(.+)$", line)
        if not m:
            continue
        base = _slugify(m.group(1))
        n = seen.get(base, 0)
        seen[base] = n + 1
        slugs.add(base if n == 0 else f"{base}-{n}")
    return slugs


def _resolve_anchor_target(referencing: Path, rel: str) -> Path | None:
    """docs/*.md files reference each other by bare filename (relative
    to docs/); everything else references docs by their docs/-prefixed
    path (relative to repo root). Try both.
    """
    for base in (referencing.parent, ROOT):
        candidate = (base / rel).resolve()
        if candidate.is_file():
            return candidate
    return None


def check_no_stale_anchors() -> None:
    """Every cross-file `#anchor` reference anywhere in the repo
    (markdown links or plain-text mentions in YAML/Python comments)
    resolves to a real file with a heading that slugs to that anchor;
    every same-file link (just `#anchor`, no filename) in a .md file
    does too. Catches the class of bug a file move/rename/split leaves
    behind — a reference nothing else here checks for.
    """
    heading_cache: dict[Path, set[str]] = {}

    def slugs_for(path: Path) -> set[str]:
        if path not in heading_cache:
            heading_cache[path] = _heading_slugs(path)
        return heading_cache[path]

    for f in sorted(ROOT.rglob("*")):
        if not f.is_file():
            continue
        if any(part in ANCHOR_SCAN_EXCLUDE_DIRS for part in f.parts):
            continue
        if f.suffix not in ANCHOR_SCAN_EXTS and f.name not in ANCHOR_SCAN_EXTRA_NAMES:
            continue

        text = re.sub(r"https?://\S+", "", read(f))  # don't chase external URLs
        rel_f = f.relative_to(ROOT)

        for rel, anchor in CROSS_FILE_ANCHOR_RE.findall(text):
            target = _resolve_anchor_target(f, rel)
            if target is None:
                fail(f"{rel_f}: references {rel}#{anchor}, which doesn't resolve to a real file")
            elif anchor not in slugs_for(target):
                fail(f"{rel_f}: references {rel}#{anchor}, but {rel} has no heading that slugs to '{anchor}'")

        if f.suffix == ".md":
            for anchor in SAME_FILE_ANCHOR_RE.findall(text):
                if anchor not in slugs_for(f):
                    fail(f"{rel_f}: references #{anchor} (same-file), but has no heading that slugs to '{anchor}'")


def main() -> int:
    check_readme()
    check_ansible_reference()
    check_molecule_matrix()
    check_deploy_flow()
    check_ci_jobs_table()
    check_no_stale_anchors()

    if errors:
        for e in errors:
            print(f"::error::{e}")
        print(f"\n{len(errors)} doc-drift issue(s) found.", file=sys.stderr)
        return 1
    print("Docs match the files/config they describe.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
