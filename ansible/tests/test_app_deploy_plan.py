"""Unit tests for filter_plugins/app_deploy_plan.py.

Run via `uv run pytest ansible/tests/ -v`. The filter is a pure function,
so it is imported directly rather than through an Ansible run.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import yaml
from ansible.errors import AnsibleFilterError

ANSIBLE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ANSIBLE_DIR / "filter_plugins"))

import app_deploy_plan as filter_mod  # noqa: E402

app_deploy_plan = filter_mod.app_deploy_plan


def volumes(*names):
    return [{"name": name} for name in names]


def plan(configs_direct=(), configs_seeded=(), scripts_direct=(), scripts_seeded=()):
    return {
        "configs": {"direct": list(configs_direct), "seeded": list(configs_seeded)},
        "scripts": {"direct": list(scripts_direct), "seeded": list(scripts_seeded)},
    }


CASES = {
    "config seeded": (
        {"volumes": volumes("data"), "configs": [{"src": "a.j2", "dest": "data/conf.yml"}]},
        plan(configs_seeded=[{"src": "a.j2", "dest": "data/conf.yml", "volume_name": "data", "volume_relpath": "conf.yml"}]),
    ),
    "config direct": (
        {"volumes": volumes("data"), "configs": [{"src": "env.j2", "dest": ".env"}]},
        plan(configs_direct=[{"src": "env.j2", "dest": ".env"}]),
    ),
    "config direct when its first path segment only starts like a volume": (
        {"volumes": volumes("data"), "configs": [{"src": "a", "dest": "database/f"}]},
        plan(configs_direct=[{"src": "a", "dest": "database/f"}]),
    ),
    "config direct when the app declares no volumes": (
        {"configs": [{"src": "a", "dest": "data/f"}]},
        plan(configs_direct=[{"src": "a", "dest": "data/f"}]),
    ),
    "seeded config keeps the whole path inside the volume": (
        {"volumes": volumes("data"), "configs": [{"src": "a", "dest": "data/sub/dir/f.yml"}]},
        plan(configs_seeded=[{"src": "a", "dest": "data/sub/dir/f.yml", "volume_name": "data", "volume_relpath": "sub/dir/f.yml"}]),
    ),
    "a trailing slash gives an empty relpath": (
        {"volumes": volumes("data"), "configs": [{"src": "a", "dest": "data/"}]},
        plan(configs_seeded=[{"src": "a", "dest": "data/", "volume_name": "data", "volume_relpath": ""}]),
    ),
    "a leading slash is not a volume": (
        {"volumes": volumes("data"), "configs": [{"src": "a", "dest": "/data/f"}]},
        plan(configs_direct=[{"src": "a", "dest": "/data/f"}]),
    ),
    "scripts direct without a scripts volume": (
        {"volumes": volumes("data"), "scripts": ["one.sh", "two.sh"]},
        plan(scripts_direct=[{"src": "one.sh", "dest": "scripts/one.sh"}, {"src": "two.sh", "dest": "scripts/two.sh"}]),
    ),
    "scripts seeded with a scripts volume": (
        {"volumes": volumes("scripts", "data"), "scripts": ["one.sh", "sub/two.sh"]},
        plan(
            scripts_seeded=[
                {"src": "one.sh", "volume_name": "scripts", "volume_relpath": "one.sh"},
                {"src": "sub/two.sh", "volume_name": "scripts", "volume_relpath": "sub/two.sh"},
            ]
        ),
    ),
    "a config under the scripts volume does not move the scripts": (
        {"volumes": volumes("scripts"), "configs": [{"src": "a", "dest": "scripts/run.sh"}], "scripts": ["b.sh"]},
        plan(
            configs_seeded=[{"src": "a", "dest": "scripts/run.sh", "volume_name": "scripts", "volume_relpath": "run.sh"}],
            scripts_seeded=[{"src": "b.sh", "volume_name": "scripts", "volume_relpath": "b.sh"}],
        ),
    ),
    "empty lists": ({"volumes": [], "configs": [], "scripts": []}, plan()),
    "missing keys": ({}, plan()),
    "only a name": ({"name": "x"}, plan()),
    "null lists count as empty": ({"volumes": None, "configs": None, "scripts": None}, plan()),
    "volumes only": ({"volumes": volumes("data")}, plan()),
    "extra keys on a config are preserved, direct and seeded": (
        {
            "volumes": volumes("data"),
            "configs": [
                {"src": "a", "dest": "data/f", "mode": "0600", "no_log": True, "force": False},
                {"src": "b", "dest": ".env", "mode": "0600", "no_log": True},
            ],
        },
        plan(
            configs_direct=[{"src": "b", "dest": ".env", "mode": "0600", "no_log": True}],
            configs_seeded=[{"src": "a", "dest": "data/f", "mode": "0600", "no_log": True, "force": False, "volume_name": "data", "volume_relpath": "f"}],
        ),
    ),
    "unknown keys on the app are ignored": (
        {"caddy": {"upstream": "x"}, "volumes": volumes("data"), "configs": [{"src": "a", "dest": ".env"}]},
        plan(configs_direct=[{"src": "a", "dest": ".env"}]),
    ),
    "order is preserved within each bucket": (
        {
            "volumes": volumes("a", "b"),
            "configs": [
                {"src": "1", "dest": "b/x"},
                {"src": "2", "dest": "c/y"},
                {"src": "3", "dest": "a/z"},
                {"src": "4", "dest": "d"},
            ],
        },
        plan(
            configs_direct=[{"src": "2", "dest": "c/y"}, {"src": "4", "dest": "d"}],
            configs_seeded=[
                {"src": "1", "dest": "b/x", "volume_name": "b", "volume_relpath": "x"},
                {"src": "3", "dest": "a/z", "volume_name": "a", "volume_relpath": "z"},
            ],
        ),
    ),
}


@pytest.mark.parametrize(("app", "expected"), CASES.values(), ids=CASES.keys())
def test_classification(app, expected):
    assert app_deploy_plan(app) == expected


def test_seeded_config_appends_its_two_keys_after_the_originals():
    app = {"volumes": volumes("data"), "configs": [{"src": "a", "dest": "data/f", "mode": "0600"}]}
    assert list(app_deploy_plan(app)["configs"]["seeded"][0]) == ["src", "dest", "mode", "volume_name", "volume_relpath"]


def test_a_config_that_already_carries_a_volume_key_has_it_replaced_in_place():
    app = {"volumes": volumes("data"), "configs": [{"src": "a", "dest": "data/f", "volume_name": "stale", "zzz": 1}]}
    seeded = app_deploy_plan(app)["configs"]["seeded"][0]
    assert seeded["volume_name"] == "data"
    assert list(seeded) == ["src", "dest", "volume_name", "zzz", "volume_relpath"]


def test_the_result_always_has_the_same_four_lists():
    result = app_deploy_plan({})
    assert {kind: sorted(buckets) for kind, buckets in result.items()} == {"configs": ["direct", "seeded"], "scripts": ["direct", "seeded"]}


def test_the_input_is_not_modified():
    app = {
        "name": "x",
        "volumes": volumes("scripts", "data"),
        "configs": [{"src": "a", "dest": "data/f", "mode": "0600"}, {"src": "b", "dest": ".env"}],
        "scripts": ["s.sh"],
    }
    before = copy.deepcopy(app)
    app_deploy_plan(app)
    assert app == before


def test_two_calls_do_not_share_state():
    first = app_deploy_plan({"volumes": volumes("data"), "configs": [{"src": "a", "dest": "data/f"}]})
    second = app_deploy_plan({})
    assert second == plan()
    assert first["configs"]["seeded"]


@pytest.mark.parametrize(
    ("app", "message"),
    [
        (
            {"name": "barevol", "volumes": volumes("data"), "configs": [{"src": "a", "dest": "data"}]},
            r"'data' of app 'barevol' names the volume 'data' itself",
        ),
        ({"name": "badcfg", "configs": {"src": "a"}}, r"'configs' of app 'badcfg' must be a list, got dict"),
        ({"name": "badscr", "scripts": "one.sh"}, r"'scripts' of app 'badscr' must be a list, got str"),
        ({"name": "badvol", "volumes": "data"}, r"'volumes' of app 'badvol' must be a list, got str"),
        ({"name": "nodest", "configs": [{"src": "a"}]}, r"a config of app 'nodest' has no string 'dest'"),
        ({"name": "intdest", "configs": [{"src": "a", "dest": 3}]}, r"a config of app 'intdest' has no string 'dest'"),
        ({"name": "strcfg", "configs": ["a"]}, r"a config of app 'strcfg' has no string 'dest'"),
        ({"name": "novol", "volumes": [{"size": 1}]}, r"a volume of app 'novol' has no 'name'"),
        ({"name": "strvol", "volumes": ["data"]}, r"a volume of app 'strvol' has no 'name'"),
    ],
)
def test_malformed_input_raises_an_error_that_names_the_app(app, message):
    with pytest.raises(AnsibleFilterError, match=message):
        app_deploy_plan(app)


@pytest.mark.parametrize("not_an_app", [None, "x", ["a"], 3])
def test_a_non_mapping_is_rejected(not_an_app):
    with pytest.raises(AnsibleFilterError, match="expected an app mapping"):
        app_deploy_plan(not_an_app)


def test_filter_module_registers_the_filter_under_its_own_name():
    assert filter_mod.FilterModule().filters() == {"app_deploy_plan": app_deploy_plan}


def _catalog():
    return yaml.safe_load((ANSIBLE_DIR / "inventory" / "group_vars" / "all" / "app_registry.yaml").read_text())["app_registry"]


@pytest.mark.parametrize("name", sorted(_catalog()))
def test_every_catalog_app_classifies_and_drops_nothing(name):
    app = {"name": name, **_catalog()[name]}
    result = app_deploy_plan(app)
    assert sum(len(bucket) for bucket in result["configs"].values()) == len(app.get("configs") or [])
    assert sum(len(bucket) for bucket in result["scripts"].values()) == len(app.get("scripts") or [])


def test_the_catalog_apps_with_scripts_split_the_way_their_volumes_say():
    catalog = _catalog()
    step_ca = app_deploy_plan({"name": "step-ca", **catalog["step-ca"]})
    minecraft = app_deploy_plan({"name": "minecraft", **catalog["minecraft"]})
    assert step_ca["scripts"]["seeded"] and not step_ca["scripts"]["direct"]
    assert minecraft["scripts"]["direct"] and not minecraft["scripts"]["seeded"]
