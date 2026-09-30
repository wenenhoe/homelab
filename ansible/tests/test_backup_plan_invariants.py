"""Invariants of ADR 0068 that no single role's tests would notice breaking.

Only `backup_plan` applies a backup default or decides that an app is backed up,
so no role, template or playbook reads an app's `backup` block or
`backup_defaults`; the Molecule stand-in that computes the plan from them is the
one place that names `backup_defaults`. And the names the decision retired appear
nowhere except in the catalog validator that refuses one of them and in the
decision records that describe the change.

Run via `uv run pytest ansible/tests/ -v`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ANSIBLE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = ANSIBLE_DIR.parent

# Code that runs a task or renders a template. Scenario data files are not here:
# they define the blocks and defaults, they don't consume the result.
CONSUMER_GLOBS = (
    "roles/*/tasks/**/*.yaml",
    "roles/*/handlers/**/*.yaml",
    "roles/*/defaults/**/*.yaml",
    "roles/*/templates/**/*.j2",
    "playbooks/*.yaml",
)

# Reading an app's own `backup` block, in any of the ways Jinja offers, or the defaults it would fall back to.
BACKUP_BLOCK_READ = re.compile(r"\.backup\b|\[['\"]backup['\"]\]|selectattr\(['\"]backup|attribute=['\"]backup|\bbackup_defaults\b")
BACKUP_DEFAULTS_ALLOWED = {"roles/molecule_helpers/tasks/resolve_backup_plan.yaml"}


def _consumer_files() -> list[Path]:
    return sorted({path for pattern in CONSUMER_GLOBS for path in ANSIBLE_DIR.glob(pattern) if path.is_file()})


def _rel(path: Path) -> str:
    return path.relative_to(ANSIBLE_DIR).as_posix()


def test_the_scan_finds_the_files_it_is_meant_to_guard():
    assert len(_consumer_files()) > 50


def test_no_consumer_reads_an_apps_backup_block_or_the_defaults():
    offenders = []
    for path in _consumer_files():
        if _rel(path) in BACKUP_DEFAULTS_ALLOWED:
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if not line.lstrip().startswith("#") and BACKUP_BLOCK_READ.search(line):
                offenders.append(f"{_rel(path)}:{number}")
    assert offenders == [], "read backup_plan instead"


@pytest.mark.parametrize(
    "line",
    [
        "{{ item.backup.volumes | default([]) }}",
        "{% if app.backup is defined %}",
        "{{ app['backup'] }}",
        "{{ apps | selectattr('backup') | list }}",
        "{{ apps | map(attribute='backup') | list }}",
        "{{ backup_defaults.cron }}",
    ],
)
def test_the_pattern_catches_each_way_of_reading_a_backup_block(line):
    assert BACKUP_BLOCK_READ.search(line)


@pytest.mark.parametrize("line", ['test: [ "CMD", "pgrep", "backup" ]', "{{ backup_plan | length }}", "{{ hostvars[h].backup_plan }}", "{{ backup_hosts }}"])
def test_the_pattern_leaves_the_plan_and_unrelated_words_alone(line):
    assert not BACKUP_BLOCK_READ.search(line)


# The variables and catalog key ADR 0068 retired. `offsite_backup_` goes as a whole prefix: the cloud copies are
# the offsite ones now, and what the SeaweedFS settings were called says nothing of them.
RETIRED = re.compile(r"(?<![A-Za-z0-9_])(extra_cloud_targets|cloud_sync_default_targets|seaweedfs_backup_hosts|offsite_backup_[A-Za-z0-9_]*)")
# Decision revisions keep the old names as history. The validator, its test and the doc that describes its rules
# name the old catalog key, and only that key, to refuse it; every other retired name stays guarded there too.
HISTORICAL = ("docs/decisions/",)
REFUSES_THE_OLD_KEY = {"tools/ci/gates/app_catalog_rules.py", "tools/tests/ci/gates/test_app_catalog_rules.py", "docs/ci.md"}
OLD_KEY = "extra_cloud_targets"
SKIPPED_DIRS = {".git", ".venv", ".ansible", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache"}


def test_no_retired_name_is_in_use():
    offenders = []
    for path in sorted(REPO_ROOT.rglob("*")):
        relative = path.relative_to(REPO_ROOT).as_posix()
        if not path.is_file() or SKIPPED_DIRS & set(path.relative_to(REPO_ROOT).parts):
            continue
        if relative.startswith(HISTORICAL) or path == Path(__file__):
            continue
        if path.name == "uv.lock" or path.suffix in {".pyc", ".png", ".jpg", ".gz", ".zip"}:
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for match in RETIRED.finditer(line):
                if not (relative in REFUSES_THE_OLD_KEY and match.group(1) == OLD_KEY):
                    offenders.append(f"{relative}:{number}: {match.group(1)}")
    assert offenders == []


@pytest.mark.parametrize(
    "name",
    [
        "extra_cloud_targets",
        "cloud_sync_default_targets",
        "seaweedfs_backup_hosts",
        "offsite_backup_cron",
        "offsite_backup_retention_days",
        "offsite_backup_s3_bucket",
        "offsite_backup_s3_endpoint",
        "offsite_backup_s3_proto",
        "offsite_backup_freshness_buffer_hours",
    ],
)
def test_the_pattern_matches_each_retired_name(name):
    assert RETIRED.search(f"x: {{{{ {name} }}}}")


@pytest.mark.parametrize(
    "text", ["seaweedfs_s3_bucket", "backup_freshness_buffer_hours", "cloud_targets", "backup_hosts", "backup_defaults", "not_offsite_backup_x"]
)
def test_the_pattern_leaves_the_replacement_names_alone(text):
    assert not RETIRED.search(text)
