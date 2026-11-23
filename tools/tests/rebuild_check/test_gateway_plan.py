"""Unit tests for rebuild_check.gateway_plan. The plans are canned `tofu show -json` documents; no Tofu runs."""

from __future__ import annotations

import json

import pytest
from rebuild_check import gateway_plan

VM = gateway_plan.GATEWAY_VM
SEED = gateway_plan.GATEWAY_SEED


def plan_with(changes: dict[str, list[str]]) -> dict:
    return {"resource_changes": [{"address": address, "change": {"actions": acts}} for address, acts in changes.items()]}


QUIET = {"module.opnsense.terraform_data.image": ["no-op"], "data.local_file.keys": ["read"], "module.ubuntu.vm": ["no-op"]}


class TestBefore:
    def test_a_plan_that_changes_nothing_passes(self):
        ok, message = gateway_plan.verdict(plan_with(QUIET), "before")
        assert (ok, message) == (True, "the plan changes nothing")

    def test_an_empty_plan_passes(self):
        assert gateway_plan.verdict({}, "before")[0]

    def test_a_change_to_any_resource_fails_and_names_it_with_its_actions(self):
        ok, message = gateway_plan.verdict(plan_with({**QUIET, "module.ubuntu.vm": ["update"], "tailscale_acl.policy": ["delete", "create"]}), "before")
        assert not ok
        assert message == "the plan changes: module.ubuntu.vm (update), tailscale_acl.policy (delete+create)"


class TestCreate:
    def test_the_gateway_vm_and_its_seed_added_and_nothing_else_passes(self):
        ok, message = gateway_plan.verdict(plan_with({**QUIET, VM: ["create"], SEED: ["create"]}), "create")
        assert (ok, message) == (True, "the plan adds the gateway VM and its seed file and nothing else")

    @pytest.mark.parametrize(
        ("changes", "named"),
        [
            pytest.param({VM: ["create"]}, "module.opnsense.proxmox_virtual_environment_vm.this (create)", id="seed-missing"),
            pytest.param({SEED: ["create"]}, "module.opnsense.proxmox_virtual_environment_file.seed[0] (create)", id="vm-missing"),
            pytest.param({VM: ["create"], SEED: ["create"], "module.ubuntu.vm": ["update"]}, "module.ubuntu.vm (update)", id="another-change"),
            pytest.param({VM: ["delete", "create"], SEED: ["create"]}, f"{VM} (delete+create)", id="vm-replaced-not-added"),
        ],
    )
    def test_anything_but_those_two_additions_fails_and_says_what_the_plan_has(self, changes, named):
        ok, message = gateway_plan.verdict(plan_with(changes), "create")
        assert not ok
        assert message.startswith("expected only the gateway VM and its seed file to be added, the plan has: ")
        assert named in message

    def test_a_plan_with_no_change_fails_in_the_create_stage(self):
        ok, message = gateway_plan.verdict(plan_with(QUIET), "create")
        assert (ok, message.endswith("the plan has: no change")) == (False, True)


class TestVariable:
    def test_a_value_is_returned_as_text(self):
        plan = {"variables": {"opnsense_image_volume_id": {"value": "tofu-images:import/OPNsense-26.1.6-nano-amd64.raw"}}}
        assert gateway_plan.variable(plan, "opnsense_image_volume_id") == "tofu-images:import/OPNsense-26.1.6-nano-amd64.raw"

    @pytest.mark.parametrize(
        "plan",
        [
            pytest.param({}, id="no-variables"),
            pytest.param({"variables": {"other": {"value": "x"}}}, id="other-variable"),
            pytest.param({"variables": {"name": {"value": None}}}, id="null"),
        ],
    )
    def test_an_absent_or_null_variable_is_none(self, plan):
        assert gateway_plan.variable(plan, "name") is None


class TestMain:
    def write(self, tmp_path, plan: dict):
        path = tmp_path / "plan.json"
        path.write_text(json.dumps(plan))
        return str(path)

    def test_verdict_prints_the_message_and_exits_zero_on_a_pass(self, tmp_path, capsys):
        assert gateway_plan.main(["verdict", "before", self.write(tmp_path, plan_with(QUIET))]) == 0
        assert capsys.readouterr().out == "the plan changes nothing\n"

    def test_verdict_exits_one_on_a_fail_and_prints_why(self, tmp_path, capsys):
        assert gateway_plan.main(["verdict", "create", self.write(tmp_path, plan_with(QUIET))]) == 1
        assert "the plan has: no change" in capsys.readouterr().out

    def test_variable_prints_the_value(self, tmp_path, capsys):
        path = self.write(tmp_path, {"variables": {"name": {"value": "x"}}})
        assert (gateway_plan.main(["variable", "name", path]), capsys.readouterr().out) == (0, "x\n")

    def test_a_missing_variable_exits_one_and_names_it(self, tmp_path, capsys):
        assert gateway_plan.main(["variable", "name", self.write(tmp_path, {})]) == 1
        assert capsys.readouterr().err == "the plan has no variable name\n"

    @pytest.mark.parametrize(
        "args",
        [
            pytest.param([], id="none"),
            pytest.param(["verdict", "later", "p.json"], id="unknown-stage"),
            pytest.param(["show", "x", "p.json"], id="unknown-command"),
        ],
    )
    def test_wrong_arguments_exit_two_with_the_usage(self, args, capsys):
        assert gateway_plan.main(args) == 2
        assert capsys.readouterr().err.startswith("usage: python3 -m rebuild_check.gateway_plan")
