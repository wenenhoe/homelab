"""Tests for filter_plugins/deploy_report.py.

The unit tests import the filter directly. The last test runs a real play in
which one host records results and then fails, so the report is built from
Ansible's own `hostvars` objects and from the facts of a host that stopped
part-way, not from dicts standing in for them.

Run via `uv run pytest ansible/tests/ -v`.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import deploy_report as filter_mod
import pytest
from ansible.errors import AnsibleFilterError

ANSIBLE_DIR = Path(__file__).resolve().parent.parent

deploy_report = filter_mod.deploy_report


def _host(declared=(), recorded=None):
    host = {"resolved_apps": [{"name": name} for name in declared]}
    if recorded is not None:
        host["compose_app_results"] = [{"name": name, "status": status} for name, status in recorded]
    return host


def test_each_hosts_apps_are_grouped_by_outcome_in_a_fixed_order():
    host = _host(declared=["a", "b", "c", "d", "e"], recorded=[("a", "ok"), ("b", "changed"), ("c", "failed"), ("e", "ok")])
    report = deploy_report(["h"], {"h": host})
    assert list(report["h"].items()) == [("failed", ["c"]), ("unfinished", ["d"]), ("changed", ["b"]), ("ok", ["a", "e"])]


def test_an_outcome_with_no_apps_is_left_out():
    report = deploy_report(["h"], {"h": _host(declared=["a"], recorded=[("a", "ok")])})
    assert report == {"h": {"ok": ["a"]}}


def test_an_app_with_no_result_is_unfinished_in_the_order_it_was_resolved():
    report = deploy_report(["h"], {"h": _host(declared=["a", "b", "c"], recorded=[("b", "ok")])})
    assert report["h"]["unfinished"] == ["a", "c"]


def test_a_host_that_recorded_nothing_lists_every_resolved_app_as_unfinished_when_another_host_did():
    hostvars = {"up": _host(declared=["a"], recorded=[("a", "changed")]), "down": _host(declared=["x", "y"])}
    report = deploy_report(["up", "down"], hostvars)
    assert report == {"up": {"changed": ["a"]}, "down": {"unfinished": ["x", "y"]}}


@pytest.mark.parametrize(
    "hostvars",
    [
        pytest.param({"h": _host(declared=["a", "b"])}, id="no result key"),
        pytest.param({"h": _host(declared=["a", "b"], recorded=[])}, id="empty results"),
        pytest.param({"h": _host(), "g": _host(declared=["a"])}, id="nothing resolved or recorded"),
    ],
)
def test_the_report_is_empty_when_no_host_recorded_anything(hostvars):
    assert deploy_report(list(hostvars), hostvars) == {}


def test_a_host_with_nothing_recorded_or_resolved_is_left_out():
    hostvars = {"up": _host(declared=["a"], recorded=[("a", "ok")]), "bare": _host()}
    assert deploy_report(["up", "bare"], hostvars) == {"up": {"ok": ["a"]}}


def test_the_last_status_recorded_for_an_app_wins_and_it_keeps_its_first_position():
    host = _host(declared=["a", "b"], recorded=[("a", "ok"), ("b", "ok"), ("a", "changed")])
    report = deploy_report(["h"], {"h": host})
    assert report == {"h": {"changed": ["a"], "ok": ["b"]}}


def test_an_app_that_was_recorded_but_not_resolved_is_still_reported():
    report = deploy_report(["h"], {"h": _host(declared=[], recorded=[("stray", "failed")])})
    assert report == {"h": {"failed": ["stray"]}}


def test_hosts_are_reported_in_the_order_given():
    hostvars = {name: _host(declared=["a"], recorded=[("a", "ok")]) for name in ("a", "b")}
    assert list(deploy_report(["b", "a"], hostvars)) == ["b", "a"]


def test_the_inputs_are_not_modified():
    hosts = ["h"]
    hostvars = {"h": _host(declared=["a", "b"], recorded=[("a", "ok"), ("a", "failed")])}
    before = copy.deepcopy((hosts, hostvars))
    deploy_report(hosts, hostvars)
    assert (hosts, hostvars) == before


@pytest.mark.parametrize(
    ("hosts", "hostvars", "match"),
    [
        pytest.param("h", {}, "hosts must be a list", id="hosts as a string"),
        pytest.param(["h"], [], "hostvars must be a mapping", id="hostvars as a list"),
        pytest.param(["h"], {}, "'h' is not in hostvars", id="unknown host"),
        pytest.param(["h"], {"h": {}}, "'h' has no resolved_apps", id="no resolved_apps"),
        pytest.param(["h"], {"h": {"resolved_apps": "a"}}, "resolved_apps must be a list", id="resolved_apps as a string"),
        pytest.param(["h"], {"h": {"resolved_apps": [{}]}}, "resolved_apps entry of 'h' needs a 'name'", id="resolved app without a name"),
        pytest.param(["h"], {"h": {"resolved_apps": [], "compose_app_results": {}}}, "compose_app_results must be a list", id="results as a mapping"),
        pytest.param(
            ["h"],
            {"h": {"resolved_apps": [], "compose_app_results": [{"name": "a"}]}},
            "needs a 'name' and a 'status'",
            id="result without a status",
        ),
        pytest.param(
            ["h"],
            {"h": {"resolved_apps": [], "compose_app_results": [{"name": "a", "status": "pending"}]}},
            "recorded 'a' with status 'pending'",
            id="result with an unknown status",
        ),
    ],
)
def test_malformed_input_is_rejected_with_a_message_naming_it(hosts, hostvars, match):
    with pytest.raises(AnsibleFilterError, match=match):
        deploy_report(hosts, hostvars)


INVENTORY = """\
all:
  vars:
    ansible_connection: local
  children:
    managed_hosts:
      hosts:
        web:
          resolved_apps: [{name: caddy}, {name: dashy}, {name: uptime}]
        db:
          resolved_apps: [{name: seaweedfs}]
"""

REPORT_PLAY = """\
- name: Record results, as the compose role does, and stop one host part-way
  hosts: managed_hosts
  gather_facts: false
  tasks:
    - name: Record the first app
      ansible.builtin.set_fact:
        compose_app_results: "{{ compose_app_results | default([]) + [{'name': first_app, 'status': first_status}] }}"
      vars:
        first_app: "{{ 'caddy' if inventory_hostname == 'web' else 'seaweedfs' }}"
        first_status: "{{ 'changed' if inventory_hostname == 'web' else 'ok' }}"
    - name: Record a second app on web
      ansible.builtin.set_fact:
        compose_app_results: "{{ compose_app_results + [{'name': 'dashy', 'status': 'ok'}] }}"
      when: inventory_hostname == 'web'
    - name: Stop web before its third app
      ansible.builtin.fail:
        msg: web stopped part-way
      when: inventory_hostname == 'web'

- name: Report
  hosts: localhost
  connection: local
  gather_facts: false
  tasks:
    - name: Write the report
      ansible.builtin.copy:
        content: "{{ groups['managed_hosts'] | deploy_report(hostvars) | to_json }}"
        dest: "{{ out_dir }}/report.json"
        mode: "0644"
"""


def _ansible_playbook() -> str:
    found = shutil.which("ansible-playbook") or str(Path(sys.executable).parent / "ansible-playbook")
    if not Path(found).exists():
        pytest.skip("ansible-playbook is not installed")
    return found


def test_a_real_play_reports_a_host_that_stopped_part_way(tmp_path):
    inventory = tmp_path / "inventory.yaml"
    inventory.write_text(INVENTORY)
    playbook = tmp_path / "report.yaml"
    playbook.write_text(REPORT_PLAY)
    out = tmp_path / "out"
    out.mkdir()
    env = {**os.environ, "ANSIBLE_HOME": str(tmp_path / "home"), "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"}

    result = subprocess.run(
        [_ansible_playbook(), "-i", str(inventory), str(playbook), "-e", f"out_dir={out}"],
        cwd=ANSIBLE_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )

    assert "web stopped part-way" in result.stdout + result.stderr
    report = json.loads((out / "report.json").read_text())
    assert report == {"web": {"unfinished": ["uptime"], "changed": ["caddy"], "ok": ["dashy"]}, "db": {"ok": ["seaweedfs"]}}
    assert list(report["web"]) == ["unfinished", "changed", "ok"]
