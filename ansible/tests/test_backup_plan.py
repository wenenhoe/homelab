"""Tests for filter_plugins/backup_plan.py.

The unit tests import the filters directly. The last three run against the
repo's real inventory: `test_backup_defaults_match_the_variables_they_replace`
keeps the new defaults equal to the variables and literals `backup_agent` still
reads, and the two after it run a real controller-only play and compare each
managed host's `backup_plan`, and the derived `backup_hosts`, with what
`backup_agent`'s normalization, the catalog's own cloud targets and
`seaweedfs_backup_hosts` say today.

Run via `uv run pytest ansible/tests/ -v`.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from ansible.errors import AnsibleFilterError

ANSIBLE_DIR = Path(__file__).resolve().parent.parent
INVENTORY_DIR = ANSIBLE_DIR / "inventory"
sys.path.insert(0, str(ANSIBLE_DIR / "filter_plugins"))

import backup_plan as filter_mod  # noqa: E402
import resolve_apps as resolver_mod  # noqa: E402

backup_plan = filter_mod.backup_plan
backup_hosts = filter_mod.backup_hosts

DEFAULTS = {
    "cron": "30 4 * * *",
    "retention_days": 7,
    "compression": "gz",
    "stop_during_backup": False,
    "cloud_targets": ["r2", "b2"],
}


def _app(name="web", **backup):
    return {"name": name, "backup": {"volumes": ["data"], **backup}}


def test_defaults_fill_every_setting_the_app_leaves_out():
    (entry,) = backup_plan([_app()], DEFAULTS)
    assert entry == {"name": "web", "volumes": ["data"], **DEFAULTS}


def test_app_settings_win_over_defaults():
    block = {"cron": "0 2 * * *", "retention_days": 30, "compression": "zst", "stop_during_backup": True, "cloud_targets": ["oci"]}
    (entry,) = backup_plan([_app(**block)], DEFAULTS)
    assert {key: entry[key] for key in block} == block


def test_a_falsy_app_value_still_wins():
    defaults = {**DEFAULTS, "stop_during_backup": True}
    (entry,) = backup_plan([_app(stop_during_backup=False, cloud_targets=[])], defaults)
    assert entry["stop_during_backup"] is False
    assert entry["cloud_targets"] == []


def test_an_app_list_replaces_the_default_list():
    (entry,) = backup_plan([_app(cloud_targets=["oci"])], DEFAULTS)
    assert entry["cloud_targets"] == ["oci"]


@pytest.mark.parametrize(
    "app",
    [
        {"name": "no-block"},
        {"name": "null-block", "backup": None},
        {"name": "no-volumes", "backup": {"stop_during_backup": True}},
        {"name": "null-volumes", "backup": {"volumes": None}},
        {"name": "empty-volumes", "backup": {"volumes": []}},
    ],
)
def test_an_app_without_backup_volumes_is_not_backed_up(app):
    assert backup_plan([app], DEFAULTS) == []


def test_order_follows_resolved_apps_and_unbacked_apps_are_skipped():
    apps = [_app("b"), {"name": "skipped"}, _app("a")]
    assert [entry["name"] for entry in backup_plan(apps, DEFAULTS)] == ["b", "a"]


def test_empty_resolved_apps_gives_an_empty_plan():
    assert backup_plan([], DEFAULTS) == []


def test_inputs_are_not_modified_and_results_share_no_list_with_them():
    apps = [_app(cloud_targets=["oci"]), _app("other")]
    apps_before, defaults_before = copy.deepcopy(apps), copy.deepcopy(DEFAULTS)
    plan = backup_plan(apps, DEFAULTS)
    assert apps == apps_before
    assert defaults_before == DEFAULTS
    plan[0]["volumes"].append("x")
    plan[0]["cloud_targets"].append("x")
    plan[1]["cloud_targets"].append("x")
    assert apps == apps_before
    assert defaults_before == DEFAULTS


@pytest.mark.parametrize(
    ("resolved_apps", "defaults", "message"),
    [
        ("web", DEFAULTS, "resolved_apps must be a list"),
        ({"name": "web"}, DEFAULTS, "resolved_apps must be a list"),
        ([], ["cron"], "backup_defaults must be a mapping"),
        ([], {k: v for k, v in DEFAULTS.items() if k not in ("cron", "compression")}, "no cron, compression"),
        ([{"backup": {"volumes": ["data"]}}], DEFAULTS, "needs a 'name'"),
        (["web"], DEFAULTS, "needs a 'name'"),
        ([{"name": "web", "backup": ["data"]}], DEFAULTS, "'web' has a backup block that is not a mapping"),
        ([{"name": "web", "backup": {"volumes": "data"}}], DEFAULTS, "'web' backup.volumes must be a list"),
        ([_app(cloud_targets="r2")], DEFAULTS, "'web' cloud_targets must be a list"),
        ([_app()], {**DEFAULTS, "cloud_targets": "r2"}, "'web' cloud_targets must be a list"),
    ],
)
def test_malformed_input_names_what_is_wrong(resolved_apps, defaults, message):
    with pytest.raises(AnsibleFilterError, match=message):
        backup_plan(resolved_apps, defaults)


def test_missing_defaults_are_reported_even_with_no_apps():
    with pytest.raises(AnsibleFilterError, match="no cloud_targets"):
        backup_plan([], {k: v for k, v in DEFAULTS.items() if k != "cloud_targets"})


HOSTVARS = {
    "alpha": {"backup_plan": [{"name": "web"}]},
    "beta": {"backup_plan": []},
    "gamma": {"backup_plan": [{"name": "db"}]},
}


def test_backup_hosts_keeps_the_order_given_and_drops_empty_plans():
    assert backup_hosts(["gamma", "beta", "alpha"], HOSTVARS) == ["gamma", "alpha"]


def test_backup_hosts_of_no_hosts_is_empty():
    assert backup_hosts([], HOSTVARS) == []


@pytest.mark.parametrize(
    ("hosts", "hostvars", "message"),
    [
        ("alpha", HOSTVARS, "hosts must be a list"),
        (["alpha"], ["alpha"], "hostvars must be a mapping"),
        (["missing"], HOSTVARS, "'missing' is not in hostvars"),
        (["alpha"], {"alpha": {}}, "'alpha' has no backup_plan"),
    ],
)
def test_backup_hosts_names_what_is_wrong(hosts, hostvars, message):
    with pytest.raises(AnsibleFilterError, match=message):
        backup_hosts(hosts, hostvars)


def test_the_plugin_exposes_exactly_its_two_filters():
    assert set(filter_mod.FilterModule().filters()) == {"backup_plan", "backup_hosts"}


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def test_backup_defaults_match_the_variables_they_replace():
    main = _load(INVENTORY_DIR / "group_vars" / "all" / "main.yaml")
    defaults = main["backup_defaults"]
    assert set(defaults) == set(filter_mod.BACKUP_SETTINGS)
    assert defaults["cron"] == main["offsite_backup_cron"]
    assert defaults["retention_days"] == main["offsite_backup_retention_days"]

    # These two are literals in backup_agent's own normalization, not variables.
    schedules = (ANSIBLE_DIR / "roles" / "backup_agent" / "tasks" / "build_schedules.yaml").read_text()
    assert re.search(r"item\.backup\.compression \| default\(['\"]" + re.escape(defaults["compression"]) + r"['\"]\)", schedules)
    assert re.search(r"item\.backup\.stop_during_backup \| default\(" + str(defaults["stop_during_backup"]).lower() + r"\)", schedules)


PLAN_PLAY = """
- hosts: localhost
  gather_facts: false
  tasks:
    - name: Write each managed host's backup_plan
      ansible.builtin.copy:
        content: "{{ hostvars[item].backup_plan | to_json }}"
        dest: "{{ out_dir }}/plan-{{ item }}.json"
        mode: "0644"
      loop: "{{ groups['managed_hosts'] }}"
    - name: Write the managed hosts and the derived backup hosts
      ansible.builtin.copy:
        content: "{{ {'managed_hosts': groups['managed_hosts'], 'backup_hosts': backup_hosts} | to_json }}"
        dest: "{{ out_dir }}/hosts.json"
        mode: "0644"
"""


def _ansible_playbook() -> str:
    found = shutil.which("ansible-playbook") or str(Path(sys.executable).parent / "ansible-playbook")
    if not Path(found).exists():
        pytest.skip("ansible-playbook is not installed")
    return found


@pytest.fixture(scope="module")
def real_inventory_output(tmp_path_factory):
    """The plans and host lists the real inventory evaluates to in a controller-only play."""
    work = tmp_path_factory.mktemp("backup_plan")
    out = work / "out"
    out.mkdir()
    playbook = work / "plan.yaml"
    playbook.write_text(PLAN_PLAY)
    env = {**os.environ, "ANSIBLE_HOME": str(work / "home"), "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"}
    result = subprocess.run(
        [_ansible_playbook(), str(playbook), "-e", f"out_dir={out}"],
        cwd=ANSIBLE_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    hosts = json.loads((out / "hosts.json").read_text())
    plans = {host: json.loads((out / f"plan-{host}.json").read_text()) for host in hosts["managed_hosts"]}
    return hosts, plans


def _expected_plan(resolved_apps: list[dict], main: dict) -> list[dict]:
    """backup_agent's normalization for one host, with the cloud targets cloud_sync fans out to."""
    out = []
    for app in resolved_apps:
        block = app.get("backup") or {}
        if not (block.get("volumes") or []):
            continue
        out.append(
            {
                "name": app["name"],
                "volumes": block["volumes"],
                "stop_during_backup": block.get("stop_during_backup", False),
                "retention_days": block.get("retention_days", main["offsite_backup_retention_days"]),
                "cron": block.get("cron", main["offsite_backup_cron"]),
                "compression": block.get("compression", "gz"),
                "cloud_targets": block.get("cloud_targets", main["backup_defaults"]["cloud_targets"]),
            }
        )
    return out


def test_plan_matches_backup_agent_normalization_for_every_host(real_inventory_output):
    _, plans = real_inventory_output
    main = _load(INVENTORY_DIR / "group_vars" / "all" / "main.yaml")
    catalog = _load(INVENTORY_DIR / "group_vars" / "all" / "app_catalog.yaml")["app_catalog"]
    assert plans, "no managed hosts"

    for host, plan in plans.items():
        compose_apps = _load(INVENTORY_DIR / "host_vars" / f"{host}.yaml")["compose_apps"]
        assert plan == _expected_plan(resolver_mod.resolve_apps(compose_apps, catalog), main), host


def test_backup_hosts_are_the_hosts_with_a_plan_in_inventory_order(real_inventory_output):
    hosts, plans = real_inventory_output
    assert hosts["backup_hosts"] == [host for host in hosts["managed_hosts"] if plans[host]]
    assert hosts["backup_hosts"], "no host backs up"
    listed = _load(INVENTORY_DIR / "host_vars" / "storage.yaml")["seaweedfs_backup_hosts"]
    assert set(hosts["backup_hosts"]) == set(listed)
