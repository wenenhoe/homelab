"""Tests for ci.gates.app_catalog_rules: one case per rule, then the real catalog.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ci.gates import app_catalog_rules as rules
from utils.app_catalog import CATALOG_KEY, BackupInventory, CatalogError, load_backup_inventory, load_catalog

GOOD = {
    "web": {
        "volumes": [{"name": "data"}, {"name": "config"}],
        "configs": [{"src": "env.j2", "dest": ".env"}],
        "backup": {"volumes": ["data"], "stop_during_backup": True},
        "routes": {"default": {"upstream": "web:8080"}, "admin": {"upstream": "web:9000", "auth": False}},
    },
    "agent": {"volumes": [{"name": "data"}]},
    "bare": {},
}


DEFAULTS = {"cron": "30 4 * * *", "retention_days": 7, "compression": "gz", "stop_during_backup": False, "cloud_targets": ["r2", "b2"]}


def inventory(**changes: object) -> BackupInventory:
    """An inventory GOOD passes against: alpha runs `web` (backed up) and so has its credentials, beta runs `agent` (not)."""
    facts = {
        "defaults": dict(DEFAULTS),
        "cloud_targets": frozenset({"r2", "b2", "oci"}),
        "managed_hosts": ("alpha", "beta"),
        "compose_apps": {"alpha": [{"name": "web"}], "beta": [{"name": "agent"}]},
        "host_vars": {
            "alpha": {
                "seaweedfs_s3_access_key": "{{ secrets_generated['seaweedfs-s3-access-key-alpha'] }}",
                "seaweedfs_s3_secret_key": "{{ secrets_generated['seaweedfs-s3-secret-key-alpha'] }}",
            },
            "beta": {},
        },
        "secrets": {"seaweedfs-s3-access-key-alpha": {"scope": "hosts/alpha"}, "seaweedfs-s3-secret-key-alpha": {"scope": "hosts/alpha"}},
    }
    facts.update(changes)
    return BackupInventory(**facts)


def broken_against(inv: BackupInventory, catalog: dict[str, dict[str, object]] | None = None) -> list[tuple[str, str]]:
    """(name, rule) of every violation of `catalog` (GOOD by default) against `inv`."""
    return [(v.name, v.rule) for v in rules.validate(GOOD if catalog is None else catalog, inv)]


def broken(app: dict[str, object]) -> list[str]:
    """The rule ids `app` breaks when it is the only entry."""
    return [violation.rule for violation in rules.validate({"a": app})]


class EachRuleTests(unittest.TestCase):
    def test_a_catalog_that_follows_every_rule_has_no_violations(self):
        self.assertEqual(rules.validate(GOOD), [])
        self.assertEqual(rules.validate({}), [])

    def test_backup_volumes_must_be_declared_volumes(self):
        self.assertEqual(broken({"volumes": [{"name": "data"}], "backup": {"volumes": ["data", "cache"]}}), ["backup-volume"])

    def test_backup_volumes_with_no_volumes_at_all_are_undeclared(self):
        self.assertEqual(broken({"backup": {"volumes": ["data"]}}), ["backup-volume"])
        self.assertEqual(broken({"volumes": [], "backup": {"volumes": ["data"]}}), ["backup-volume"])

    def test_every_undeclared_backup_volume_is_reported(self):
        found = rules.validate({"a": {"volumes": [{"name": "x"}], "backup": {"volumes": ["p", "x", "q"]}}})
        self.assertEqual([(v.rule, "`p`" in v.message, "`q`" in v.message) for v in found], [("backup-volume", True, False), ("backup-volume", False, True)])

    def test_a_backup_block_must_name_a_volume(self):
        for backup in ({}, {"stop_during_backup": True}, {"volumes": None}, {"volumes": []}):
            with self.subTest(backup=backup):
                self.assertEqual(broken({"volumes": [{"name": "data"}], "backup": backup}), ["backup-volumes"])

    def test_an_app_with_no_backup_block_is_not_asked_for_volumes(self):
        self.assertEqual(broken({"volumes": [{"name": "data"}]}), [])
        self.assertEqual(broken({"volumes": [{"name": "data"}], "backup": None}), [])

    def test_each_backup_setting_must_keep_its_shape(self):
        cases = {
            "cloud_targets": ["r2", [["r2"]], [""], [1], {"r2": 1}, None],
            "retention_days": [0, -1, "7", True, 1.5, None, [7]],
            "compression": ["bz2", "", "GZ", None, ["gz"]],
            "stop_during_backup": ["yes", 1, 0, "true", None],
            "cron": ["", "  ", 5, None, ["* * * * *"]],
        }
        for key, values in cases.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    found = rules.validate({"a": {"volumes": [{"name": "data"}], "backup": {"volumes": ["data"], key: value}}})
                    self.assertEqual([(v.rule, key in v.message) for v in found], [("backup-shape", True)])

    def test_an_unknown_backup_key_is_refused_with_the_nearest_valid_one(self):
        found = rules.validate({"a": {"volumes": [{"name": "d"}], "backup": {"volumes": ["d"], "retention_day": 3}}})
        self.assertEqual(
            [(v.rule, "`backup.retention_day`" in v.message, "did you mean `retention_days`" in v.message) for v in found],
            [("backup-unknown-key", True, True)],
        )

    def test_an_unknown_key_with_nothing_close_gets_no_suggestion(self):
        found = rules.validate({"a": {"volumes": [{"name": "d"}], "backup": {"volumes": ["d"], "frequency": 3}}})
        self.assertEqual([(v.rule, "did you mean" in v.message) for v in found], [("backup-unknown-key", False)])

    def test_every_unknown_backup_key_is_reported(self):
        block = {"volumes": ["d"], "crn": "0 4 * * *", "compresion": "gz", "cron": "0 4 * * *"}
        self.assertEqual(broken({"volumes": [{"name": "d"}], "backup": block}), ["backup-unknown-key", "backup-unknown-key"])

    def test_a_key_that_is_not_text_is_reported_not_a_crash(self):
        self.assertEqual(broken({"volumes": [{"name": "d"}], "backup": {"volumes": ["d"], 1: "x"}}), ["backup-unknown-key"])

    def test_every_backup_key_together_is_accepted(self):
        block = {"volumes": ["d"], "cron": "0 4 * * *", "retention_days": 3, "compression": "zst", "stop_during_backup": True, "cloud_targets": ["oci"]}
        self.assertEqual(broken({"volumes": [{"name": "d"}], "backup": block}), [])

    def test_the_old_cloud_targets_key_is_one_violation_not_also_an_unknown_key(self):
        block = {"volumes": ["d"], rules.LEGACY_CLOUD_TARGETS_KEY: ["oci"]}
        self.assertEqual(broken({"volumes": [{"name": "d"}], "backup": block}), ["legacy-cloud-targets-key"])

    def test_every_valid_value_of_a_backup_setting_is_accepted(self):
        valid = {
            "cloud_targets": [[], ["oci"], ["r2", "b2"]],
            "retention_days": [1, 7, 365],
            "compression": ["gz", "zst", "none"],
            "stop_during_backup": [True, False],
            "cron": ["0 4 * * *", "*/5 * * * 1-5"],
        }
        for key, values in valid.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    self.assertEqual(broken({"volumes": [{"name": "data"}], "backup": {"volumes": ["data"], key: value}}), [])

    def test_every_route_must_name_an_upstream(self):
        for route in ({}, {"auth": False}, {"upstream": ""}, {"upstream": "  "}, {"upstream": None}, {"upstream": 8080}):
            with self.subTest(route=route):
                self.assertEqual(broken({rules.ROUTES_KEY: {"default": route}}), ["route-upstream"])

    def test_a_missing_upstream_names_its_route(self):
        found = rules.validate({"a": {rules.ROUTES_KEY: {"web": {"upstream": "a:1"}, "admin": {"auth": False}}}})
        self.assertEqual([(v.rule, "`admin`" in v.message) for v in found], [("route-upstream", True)])

    def test_a_route_map_under_the_old_key_is_refused(self):
        self.assertEqual(broken({rules.LEGACY_ROUTES_KEY: {"default": {"upstream": "web:80"}}}), ["legacy-route-key"])
        self.assertEqual(
            broken({rules.LEGACY_ROUTES_KEY: {"default": {"upstream": "web:80"}}, rules.ROUTES_KEY: {"default": {"upstream": "web:80"}}}), ["legacy-route-key"]
        )

    def test_the_old_key_holding_something_else_is_not_a_route_map(self):
        self.assertEqual(broken({rules.LEGACY_ROUTES_KEY: {}}), [])
        self.assertEqual(broken({rules.LEGACY_ROUTES_KEY: {"volumes": []}}), [])

    def test_cloud_targets_under_the_old_key_are_refused(self):
        volumes = {"volumes": [{"name": "d"}], "backup": {"volumes": ["d"]}}
        self.assertEqual(broken({**volumes, "backup": {"volumes": ["d"], rules.LEGACY_CLOUD_TARGETS_KEY: ["oci"]}}), ["legacy-cloud-targets-key"])
        self.assertEqual(
            broken({**volumes, "backup": {"volumes": ["d"], rules.LEGACY_CLOUD_TARGETS_KEY: ["oci"], rules.CLOUD_TARGETS_KEY: ["oci"]}}),
            ["legacy-cloud-targets-key"],
        )

    def test_cloud_targets_under_the_new_key_are_fine(self):
        self.assertEqual(broken({"volumes": [{"name": "d"}], "backup": {"volumes": ["d"], rules.CLOUD_TARGETS_KEY: ["oci"]}}), [])

    def test_an_app_with_no_routes_is_fine(self):
        self.assertEqual(broken({"volumes": [{"name": "data"}]}), [])
        self.assertEqual(broken({rules.ROUTES_KEY: {}}), [])

    def test_wrong_shapes_are_reported_instead_of_crashing(self):
        cases = {
            "volumes-shape": [{"volumes": "data"}, {"volumes": ["data"]}, {"volumes": [{"size": 1}]}, {"volumes": [{"name": ""}]}],
            "backup-shape": [{"backup": ["data"]}, {"backup": {"volumes": "data"}}, {"backup": {"volumes": [1]}}, {"backup": {"volumes": [""]}}],
            "routes-shape": [{rules.ROUTES_KEY: ["web:80"]}, {rules.ROUTES_KEY: {"default": "web:80"}}],
        }
        for rule, apps in cases.items():
            for app in apps:
                with self.subTest(rule=rule, app=app):
                    self.assertEqual(broken(app), [rule])

    def test_malformed_volumes_do_not_also_fail_the_subset_check(self):
        self.assertEqual(broken({"volumes": "data", "backup": {"volumes": ["data"]}}), ["volumes-shape"])

    def test_every_violation_in_an_app_is_reported_not_just_the_first(self):
        found = broken({"volumes": [{"name": "data"}], "backup": {"volumes": ["cache"]}, rules.ROUTES_KEY: {"default": {}}})
        self.assertEqual(sorted(found), ["backup-volume", "route-upstream"])

    def test_violations_name_the_app_and_come_in_app_order(self):
        found = rules.validate({"ok": GOOD["web"], "one": {rules.ROUTES_KEY: {"r": {}}}, "two": {"backup": {"volumes": ["x"]}}})
        self.assertEqual([(v.name, v.rule) for v in found], [("one", "route-upstream"), ("two", "backup-volume")])


class AgainstTheInventoryTests(unittest.TestCase):
    def test_a_catalog_and_inventory_that_agree_have_no_violations(self):
        self.assertEqual(broken_against(inventory()), [])

    def test_without_an_inventory_only_the_catalog_rules_run(self):
        self.assertEqual(rules.validate(GOOD), [])
        self.assertEqual(rules.validate(GOOD, None), [])

    def test_a_cloud_target_the_storage_host_does_not_define_is_refused(self):
        catalog = {**GOOD, "web": {**GOOD["web"], "backup": {"volumes": ["data"], "cloud_targets": ["r2", "gcs"]}}}
        found = rules.validate(catalog, inventory())
        self.assertEqual([(v.name, v.rule, "`gcs`" in v.message, "`r2`" in v.message) for v in found], [("web", "cloud-target", True, False)])

    def test_every_unknown_cloud_target_is_reported(self):
        catalog = {"web": {**GOOD["web"], "backup": {"volumes": ["data"], "cloud_targets": ["x", "r2", "y"]}}}
        self.assertEqual(broken_against(inventory(), catalog), [("web", "cloud-target"), ("web", "cloud-target")])

    def test_an_unknown_cloud_target_in_the_defaults_is_refused_under_its_own_name(self):
        self.assertEqual(broken_against(inventory(defaults={**DEFAULTS, "cloud_targets": ["r2", "gcs"]})), [("backup_defaults", "cloud-target")])

    def test_a_malformed_cloud_target_list_is_a_shape_problem_only(self):
        catalog = {"web": {**GOOD["web"], "backup": {"volumes": ["data"], "cloud_targets": "r2"}}}
        self.assertEqual(broken_against(inventory(), catalog), [("web", "backup-shape")])

    def test_the_defaults_must_supply_every_setting_in_its_shape(self):
        missing = {key: value for key, value in DEFAULTS.items() if key not in ("cron", "compression")}
        found = rules.validate(GOOD, inventory(defaults=missing))
        self.assertEqual([(v.name, v.rule, "`cron`" in v.message and "`compression`" in v.message) for v in found], [("backup_defaults", "backup-shape", True)])
        self.assertEqual(broken_against(inventory(defaults={**DEFAULTS, "retention_days": 0, "compression": "bz2"})), [("backup_defaults", "backup-shape")] * 2)

    def test_an_unknown_key_in_the_defaults_is_refused_under_their_own_name(self):
        for extra in ({"retention_day": 7}, {"volumes": ["d"]}):
            with self.subTest(extra=extra):
                self.assertEqual(broken_against(inventory(defaults={**DEFAULTS, **extra})), [("backup_defaults", "backup-unknown-key")])

    def test_the_old_cloud_targets_key_in_the_defaults_is_refused(self):
        found = broken_against(inventory(defaults={**DEFAULTS, rules.LEGACY_CLOUD_TARGETS_KEY: ["r2"]}))
        self.assertEqual(found, [("backup_defaults", "legacy-cloud-targets-key")])

    def test_a_host_override_keeps_the_same_keys_and_shapes_under_the_hosts_name(self):
        cases = {
            "an unknown key": ({"retention_day": 3}, [("alpha", "backup-unknown-key")]),
            "the old cloud key": ({rules.LEGACY_CLOUD_TARGETS_KEY: ["oci"]}, [("alpha", "legacy-cloud-targets-key")]),
            "a bad setting": ({"retention_days": "3"}, [("alpha", "backup-shape")]),
            "a bad setting and an unknown key": ({"retention_days": 0, "frequency": 1}, [("alpha", "backup-shape"), ("alpha", "backup-unknown-key")]),
            "volumes that are not a list": ({"volumes": "data"}, [("alpha", "backup-shape")]),
            "volumes of the wrong type": ({"volumes": [1]}, [("alpha", "backup-shape")]),
            "a valid override": ({"cron": "0 1 * * *", "retention_days": 30, "cloud_targets": ["oci"]}, []),
            "volumes emptied to switch the backup off": ({"volumes": []}, []),
            "volumes replaced": ({"volumes": ["data"]}, []),
        }
        for label, (override, expected) in cases.items():
            with self.subTest(label):
                inv = inventory(managed_hosts=("alpha",), compose_apps={"alpha": [{"name": "web", "backup": override}]})
                found = broken_against(inv)
                self.assertEqual([f for f in found if f[0] == "alpha" and f[1] != "backup-host-credentials"], expected)

    def test_a_host_override_that_is_not_a_mapping_is_refused_and_a_null_one_is_fine(self):
        for override, expected in (("data", [("alpha", "backup-shape")]), (["data"], [("alpha", "backup-shape")]), (None, [])):
            with self.subTest(override=override):
                inv = inventory(managed_hosts=("alpha",), compose_apps={"alpha": [{"name": "web", "backup": override}]})
                self.assertEqual([f for f in broken_against(inv) if f[1] != "backup-host-credentials"], expected)

    def test_a_violation_in_an_override_names_the_app_and_the_key(self):
        inv = inventory(managed_hosts=("alpha",), compose_apps={"alpha": [{"name": "web", "backup": {"retention_day": 3}}]})
        (found,) = [v for v in rules.validate(GOOD, inv) if v.rule == "backup-unknown-key"]
        self.assertEqual((found.name, "`web.backup.retention_day`" in found.message, "retention_days" in found.message), ("alpha", True, True))

    def test_backup_hosts_are_the_hosts_running_a_backed_up_app_in_inventory_order(self):
        inv = inventory(
            managed_hosts=("beta", "alpha", "gamma"), compose_apps={"alpha": [{"name": "web"}], "beta": [{"name": "agent"}], "gamma": [{"name": "web"}]}
        )
        self.assertEqual(rules.backup_hosts(GOOD, inv), ["alpha", "gamma"])

    def test_a_host_entry_can_take_an_app_out_of_the_backup_or_put_it_in(self):
        cases = {
            "removes": ([{"name": "web", "backup": {"volumes": []}}], []),
            "nulls the block": ([{"name": "web", "backup": None}], []),
            "keeps": ([{"name": "web", "backup": {"cron": "0 1 * * *"}}], ["alpha"]),
            "replaces the volumes": ([{"name": "agent", "backup": {"volumes": ["data"]}}], ["alpha"]),
            "an app the catalog lacks": ([{"name": "unknown"}], []),
        }
        for label, (entries, expected) in cases.items():
            with self.subTest(label):
                inv = inventory(managed_hosts=("alpha",), compose_apps={"alpha": entries})
                self.assertEqual(rules.backup_hosts(GOOD, inv), expected)

    def test_a_backup_host_needs_each_secret_scoped_to_itself(self):
        for missing in ("seaweedfs-s3-access-key-alpha", "seaweedfs-s3-secret-key-alpha"):
            with self.subTest(missing=missing):
                secrets = {name: entry for name, entry in inventory().secrets.items() if name != missing}
                found = rules.validate(GOOD, inventory(secrets=secrets))
                self.assertEqual([(v.name, v.rule, missing in v.message) for v in found], [("alpha", "backup-host-credentials", True)])

    def test_a_secret_scoped_to_another_host_does_not_count(self):
        secrets = {**inventory().secrets, "seaweedfs-s3-access-key-alpha": {"scope": "hosts/beta"}}
        self.assertEqual(broken_against(inventory(secrets=secrets)), [("alpha", "backup-host-credentials")])

    def test_a_backup_host_needs_both_host_vars_taken_from_its_own_secrets(self):
        ok = inventory().host_vars["alpha"]
        wrong = "{{ secrets_generated['seaweedfs-s3-access-key-beta'] }}"
        cases = {
            "no access key": {"seaweedfs_s3_secret_key": ok["seaweedfs_s3_secret_key"]},
            "no secret key": {"seaweedfs_s3_access_key": ok["seaweedfs_s3_access_key"]},
            "another host's secret": {**ok, "seaweedfs_s3_access_key": wrong},
            "a literal": {**ok, "seaweedfs_s3_secret_key": "hunter2"},
        }
        for label, host_vars in cases.items():
            with self.subTest(label):
                found = rules.validate(GOOD, inventory(host_vars={"alpha": host_vars, "beta": {}}))
                self.assertEqual([(v.name, v.rule) for v in found], [("alpha", "backup-host-credentials")])

    def test_a_host_with_no_backed_up_app_needs_no_credentials(self):
        inv = inventory(managed_hosts=("beta",), secrets={}, host_vars={"beta": {}})
        self.assertEqual(broken_against(inv), [])

    def test_every_missing_credential_is_reported(self):
        found = broken_against(inventory(secrets={}, host_vars={"alpha": {}, "beta": {}}))
        self.assertEqual(found, [("alpha", "backup-host-credentials")] * 4)


class MainTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "catalog.yaml"

    def run_main(self, text: str | None, inv: BackupInventory | Exception | None = None) -> tuple[int, str, str]:
        if text is not None:
            self.path.write_text(text)
        out, err = io.StringIO(), io.StringIO()
        loader = {"side_effect": inv} if isinstance(inv, Exception) else {"return_value": inv or inventory()}
        with patch.object(rules, "CATALOG_PATH", self.path), patch.object(rules, "load_backup_inventory", **loader), redirect_stdout(out), redirect_stderr(err):
            code = rules.main()
        return code, out.getvalue(), err.getvalue()

    def test_passes_a_clean_catalog(self):
        code, out, err = self.run_main(f"{CATALOG_KEY}:\n  a:\n    volumes: [{{ name: data }}]\n    backup: {{ volumes: [data] }}\n")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("every app follows the catalog rules", out)

    def test_fails_and_names_each_violation_and_its_rule(self):
        code, _, err = self.run_main(
            f"{CATALOG_KEY}:\n  a:\n    backup: {{ volumes: [data] }}\n  b:\n    {rules.ROUTES_KEY}:\n      default: {{ auth: false }}\n"
        )
        self.assertEqual(code, 1)
        self.assertIn("::error::a:", err)
        self.assertIn("[backup-volume]", err)
        self.assertIn("::error::b:", err)
        self.assertIn("[route-upstream]", err)
        self.assertIn("2 rule violation(s)", err)

    def test_fails_on_an_unreadable_catalog(self):
        code, _, err = self.run_main(None)
        self.assertEqual(code, 1)
        self.assertIn("::error::can't read", err)

    def test_fails_on_an_inventory_violation_and_names_the_rule(self):
        code, _, err = self.run_main(f"{CATALOG_KEY}:\n  a:\n    volumes: [{{ name: data }}]\n    backup: {{ volumes: [data], cloud_targets: [gcs] }}\n")
        self.assertEqual(code, 1)
        self.assertIn("::error::a:", err)
        self.assertIn("[cloud-target]", err)

    def test_fails_on_an_unreadable_inventory(self):
        code, _, err = self.run_main(f"{CATALOG_KEY}:\n  a: {{}}\n", CatalogError("can't read ansible/inventory/inventory.yaml"))
        self.assertEqual(code, 1)
        self.assertIn("::error::can't read ansible/inventory/inventory.yaml", err)

    def test_fails_on_a_repeated_app_name(self):
        code, _, err = self.run_main(f"{CATALOG_KEY}:\n  a: {{}}\n  a: {{}}\n")
        self.assertEqual(code, 1)
        self.assertIn("duplicate key", err)


class RealCatalogTests(unittest.TestCase):
    def test_the_real_catalog_follows_every_rule(self):
        self.assertEqual(rules.validate(load_catalog()), [])

    def test_the_real_catalog_and_inventory_agree(self):
        self.assertEqual(rules.validate(load_catalog(), load_backup_inventory()), [])

    def test_the_real_backup_hosts_are_not_empty_and_are_managed_hosts(self):
        inv, catalog = load_backup_inventory(), load_catalog()
        hosts = rules.backup_hosts(catalog, inv)
        self.assertTrue(hosts)
        self.assertTrue(set(hosts) <= set(inv.managed_hosts))

    def test_main_passes_on_the_real_catalog(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(rules.main(), 0)


if __name__ == "__main__":
    unittest.main()
