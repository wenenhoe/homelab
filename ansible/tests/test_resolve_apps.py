"""Tests for filter_plugins/resolve_apps.py.

The unit tests import the filter directly. `test_matches_catalog_merge_for_every_host`
runs a real controller-only play against the repo's inventory and compares each
managed host's `resolved_apps` with the merge that `roles/compose/tasks/preinit.yaml`
performed before the resolver existed: `combine(recursive=True)` of the catalog
entry under the host's entry.

Run via `uv run pytest ansible/tests/ -v`.
"""

from __future__ import annotations

import copy
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from ansible.errors import AnsibleFilterError

ANSIBLE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ANSIBLE_DIR / "filter_plugins"))

import resolve_apps as filter_mod  # noqa: E402

resolve_apps = filter_mod.resolve_apps


CATALOG = {
    "web": {
        "volumes": [{"name": "data"}, {"name": "config"}],
        "configs": [{"src": "env.j2", "dest": ".env"}],
        "backup": {"volumes": ["data"], "cron": "0 3 * * *"},
        "routes": {"default": {"upstream": "web:8080", "auth": True}},
    },
    "db": {"volumes": [{"name": "data"}]},
}


def test_host_route_joins_catalog_route():
    (app,) = resolve_apps([{"name": "web", "routes": {"default": {"host": "web"}}}], CATALOG)
    assert app["routes"] == {"default": {"upstream": "web:8080", "auth": True, "host": "web"}}


def test_nested_dicts_merge_and_host_scalar_wins():
    (app,) = resolve_apps([{"name": "web", "backup": {"cron": "0 5 * * *"}, "routes": {"default": {"auth": False}}}], CATALOG)
    assert app["backup"] == {"volumes": ["data"], "cron": "0 5 * * *"}
    assert app["routes"]["default"] == {"upstream": "web:8080", "auth": False}


def test_host_list_replaces_catalog_list():
    (app,) = resolve_apps([{"name": "web", "volumes": [{"name": "only"}], "backup": {"volumes": []}}], CATALOG)
    assert app["volumes"] == [{"name": "only"}]
    assert app["backup"]["volumes"] == []


def test_catalog_list_is_kept_when_host_names_none():
    (app,) = resolve_apps([{"name": "web"}], CATALOG)
    assert app["volumes"] == CATALOG["web"]["volumes"]
    assert app["configs"] == CATALOG["web"]["configs"]


def test_app_without_catalog_entry_resolves_to_itself():
    entry = {"name": "adhoc", "routes": {"default": {"host": "adhoc"}}}
    assert resolve_apps([entry], CATALOG) == [entry]


def test_null_catalog_entry_is_treated_as_empty():
    assert resolve_apps([{"name": "x"}], {"x": None}) == [{"name": "x"}]


def test_order_follows_compose_apps_and_repeats_are_kept():
    names = [app["name"] for app in resolve_apps([{"name": "db"}, {"name": "web"}, {"name": "db"}], CATALOG)]
    assert names == ["db", "web", "db"]


def test_empty_compose_apps_resolves_to_empty_list():
    assert resolve_apps([], CATALOG) == []


def test_inputs_are_not_modified():
    apps = [{"name": "web", "volumes": [{"name": "x"}], "routes": {"default": {"host": "web"}}}, {"name": "db"}]
    catalog_before, apps_before = copy.deepcopy(CATALOG), copy.deepcopy(apps)
    resolve_apps(apps, CATALOG)
    assert catalog_before == CATALOG
    assert apps == apps_before


@pytest.mark.parametrize(
    ("compose_apps", "catalog", "message"),
    [
        ("web", CATALOG, "must be a list"),
        (None, CATALOG, "must be a list"),
        ([{"name": "web"}], ["web"], "keyed by app name"),
        ([{"host": "x"}], CATALOG, "needs a 'name'"),
        (["web"], CATALOG, "needs a 'name'"),
        ([{"name": "web"}], {"web": ["not", "a", "dict"]}, "must be a mapping"),
    ],
)
def test_malformed_input_raises_a_filter_error(compose_apps, catalog, message):
    with pytest.raises(AnsibleFilterError, match=message):
        resolve_apps(compose_apps, catalog)


def test_filter_is_registered_under_its_name():
    assert filter_mod.FilterModule().filters() == {"resolve_apps": resolve_apps}


# The play reads every managed host's value from a controller-only play, which
# also keeps the lazily-templated `resolved_apps` readable before any host play.
EQUALITY_PLAY = """
- hosts: localhost
  gather_facts: false
  tasks:
    - name: Compare resolved_apps with the catalog merge
      ansible.builtin.assert:
        that: expected == actual
        quiet: true
        fail_msg: "resolved_apps differs from the catalog merge on {{ item }}: {{ differing }}"
      loop: "{{ groups['managed_hosts'] }}"
      vars:
        actual: "{{ hostvars[item].resolved_apps }}"
        expected: >-
          {%- set out = [] -%}
          {%- for app in hostvars[item].compose_apps -%}
          {%- set _ = out.append((app_catalog[app.name] | default({})) | combine(app, recursive=True)) -%}
          {%- endfor -%}
          {{ out }}
        differing: >-
          {%- set names = [] -%}
          {%- for e, a in expected | zip(actual) -%}
          {%- if e != a -%}{%- set _ = names.append(e.name) -%}{%- endif -%}
          {%- endfor -%}
          {{ names }}
"""


def _ansible_playbook() -> str:
    found = shutil.which("ansible-playbook") or str(Path(sys.executable).parent / "ansible-playbook")
    if not Path(found).exists():
        pytest.skip("ansible-playbook is not installed")
    return found


def test_matches_catalog_merge_for_every_host(tmp_path):
    playbook = tmp_path / "equality.yaml"
    playbook.write_text(EQUALITY_PLAY)
    env = {**os.environ, "ANSIBLE_HOME": str(tmp_path / "home"), "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"}
    result = subprocess.run([_ansible_playbook(), str(playbook)], cwd=ANSIBLE_DIR, env=env, capture_output=True, text=True, timeout=300, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
