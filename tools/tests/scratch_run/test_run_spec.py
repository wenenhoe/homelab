from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml
from scratch_run.spec import CanaryVm, SpecError, load_spec, parse_spec
from scratch_run_fakes import RUNS

GOOD = {
    "name": "sample",
    "description": "What the run shows",
    "gateway": {"vlans": [20, 70], "play_vars": {"opnsense_gateway_operator_hosts": ["192.168.40.250"]}},
    "block_rule": {"source": "192.168.20.0/24", "destination": "192.168.20.1", "protocol": "UDP", "port": 53},
    "steps": [
        {"id": "apply", "play": "apply"},
        {"id": "check", "play": "check"},
        {"id": "services", "flows": {"tags": ["services"], "ids": ["services-gateway-dns"]}, "expect": "fail"},
        {"id": "block-on", "block": "present"},
        {"id": "vlans", "vlans": "check"},
    ],
}


def broken(change) -> dict:
    spec = copy.deepcopy(GOOD)
    change(spec)
    return spec


def test_the_committed_specs_load_against_the_committed_flow_list(subtests):
    paths = sorted(RUNS.glob("*.yaml"))
    assert paths, "no spec is committed"
    for path in paths:
        with subtests.test(spec=path.name):
            assert load_spec(path).name == path.stem


def test_a_good_spec_is_read_with_its_defaults():
    spec = parse_spec(GOOD)
    apply, check, services, block, vlans = spec.steps
    assert (spec.vlans, spec.block_rule.port) == ((20, 70), 53)
    assert (apply.expect, check.expect, services.expect, block.expect, vlans.expect) == ("ok", "unchanged", "fail", "", "")
    assert (vlans.kind, vlans.mode) == ("vlans", "check")
    assert (services.tags, services.flow_ids) == (("services",), ("services-gateway-dns",))


@pytest.mark.parametrize(
    ("data", "message"),
    [
        pytest.param(broken(lambda s: s.update(colour="red")), "unknown key `colour`", id="unknown-top-key"),
        pytest.param(broken(lambda s: s.update(name="Bad Name")), "`name` must be lowercase", id="bad-name"),
        pytest.param(broken(lambda s: s.update(description=" ")), "`description` must say", id="empty-description"),
        pytest.param(broken(lambda s: s.update(steps=[])), "`steps` must be a non-empty list", id="no-steps"),
        pytest.param(broken(lambda s: s["gateway"].update(vlans=[20, 20])), "distinct VLAN tags", id="repeated-vlan"),
        pytest.param(broken(lambda s: s["gateway"].update(vlans=[5000])), "1 to 4094", id="vlan-out-of-range"),
        pytest.param(
            broken(lambda s: s["gateway"]["play_vars"].update(other="x")), "only variables that start with `opnsense_gateway_`", id="foreign-play-var"
        ),
        pytest.param(broken(lambda s: s["gateway"]["play_vars"].update(opnsense_gateway_api_port=1)), "which the backend sets", id="backend-play-var"),
        pytest.param(broken(lambda s: s["gateway"]["play_vars"].update(opnsense_gateway_x=object())), "JSON can carry", id="play-var-not-json"),
        pytest.param(broken(lambda s: s["block_rule"].update(protocol="ICMP")), "TCP or UDP", id="bad-protocol"),
        pytest.param(broken(lambda s: s["block_rule"].update(port=0)), "port number", id="bad-port"),
        pytest.param(broken(lambda s: s["block_rule"].update(source="elsewhere")), "`block_rule.source` must be", id="bad-source"),
        pytest.param(broken(lambda s: s.pop("block_rule")), "a block step needs `block_rule`", id="block-without-rule"),
        pytest.param(broken(lambda s: s["steps"].pop(3)), "no step uses it", id="rule-without-block"),
        pytest.param(broken(lambda s: s["steps"][1].update(id="apply")), "`apply` is used twice", id="repeated-step-id"),
        pytest.param(broken(lambda s: s["steps"][0].update(flows={"tags": ["x"]})), "exactly one of play, flows, block, vlans, vm", id="two-kinds"),
        pytest.param(broken(lambda s: s["steps"][0].update(play="destroy")), "one of apply, check", id="bad-play-mode"),
        pytest.param(broken(lambda s: s["steps"][0].update(expect="pass")), "one of ok, unchanged, changed", id="wrong-play-expect"),
        pytest.param(broken(lambda s: s["steps"][3].update(expect="ok")), "takes no `expect`", id="block-expect"),
        pytest.param(broken(lambda s: s["steps"][4].update(expect="pass")), "takes no `expect`", id="vlans-expect"),
        pytest.param(broken(lambda s: s["steps"][4].update(vlans="apply")), "`vlans` to be one of check", id="bad-vlans-mode"),
        pytest.param(broken(lambda s: s["gateway"].pop("vlans")), "a vlans step needs `gateway.vlans`", id="vlans-step-without-the-list"),
        pytest.param(broken(lambda s: s["steps"][2].update(flows={})), "mapping of `tags` and/or `ids`", id="empty-flows"),
        pytest.param(broken(lambda s: s["steps"][2].update(flows={"tags": []})), "non-empty list of names", id="empty-tags"),
        pytest.param(broken(lambda s: s["steps"][2].update(flows={"tags": ["no-such-tag"]})), "tag `no-such-tag`, which no flow has", id="unknown-tag"),
        pytest.param(
            broken(lambda s: s["steps"][2].update(flows={"ids": ["no-such-flow"]})), "flow `no-such-flow`, which the flow list does not have", id="unknown-flow"
        ),
        pytest.param(broken(lambda s: s["steps"][0].update(id="Not Valid")), "needs an `id`", id="bad-step-id"),
    ],
)
def test_a_mistake_is_refused_with_its_reason(data, message):
    with pytest.raises(SpecError, match=message):
        parse_spec(data)


def test_every_problem_is_named_at_once():
    data = broken(lambda s: (s.pop("block_rule"), s.update(name="Bad", steps=[{"id": "a", "play": "x"}, {"id": "b"}])))
    with pytest.raises(SpecError) as raised:
        parse_spec(data)
    assert len(str(raised.value).splitlines()) == 3


def test_a_spec_that_is_not_a_mapping_is_refused():
    with pytest.raises(SpecError, match="must be a mapping"):
        parse_spec(["a"])


def test_a_repeated_key_in_the_file_is_refused(tmp_path_factory):
    path = tmp_path_factory.mktemp("specs") / "twice.yaml"
    path.write_text("name: a\nname: b\n")
    with pytest.raises(SpecError, match="duplicate key"):
        load_spec(path)


def test_a_missing_file_is_refused(tmp_path_factory):
    with pytest.raises(SpecError, match="cannot be read"):
        load_spec(tmp_path_factory.mktemp("specs") / "absent.yaml")


def test_a_spec_with_no_flow_step_does_not_need_the_flow_list(tmp_path):
    data = {"name": "play-only", "description": "d", "steps": [{"id": "apply", "play": "apply"}]}
    assert parse_spec(data, flows_path=tmp_path / "absent.yaml").steps[0].mode == "apply"


def test_a_flow_step_with_an_unreadable_flow_list_is_refused(tmp_path):
    bad = tmp_path / "flows.yaml"
    bad.write_text(yaml.safe_dump({"zones": {}}))
    with pytest.raises(SpecError, match="the flow list cannot be read"):
        parse_spec(GOOD, flows_path=Path(bad))


VM_SPEC = {
    "name": "canary-vm",
    "description": "A VM is the services canary",
    "canary_vm": {"zone": "services"},
    "steps": [{"id": "vm-up", "vm": "up"}, {"id": "flows", "flows": {"tags": ["services"]}}],
}


def vm_broken(change) -> dict:
    spec = copy.deepcopy(VM_SPEC)
    change(spec)
    return spec


def test_a_canary_vm_and_its_step_are_read():
    spec = parse_spec(VM_SPEC)
    assert spec.canary_vm == CanaryVm("services")
    step = spec.steps[0]
    assert (step.id, step.kind, step.mode, step.expect) == ("vm-up", "vm", "up", "")


def test_a_spec_with_no_canary_vm_has_none():
    assert parse_spec(GOOD).canary_vm is None


@pytest.mark.parametrize(
    ("data", "message"),
    [
        pytest.param(vm_broken(lambda s: s.pop("canary_vm")), "a vm step needs `canary_vm`", id="vm-step-without-canary-vm"),
        pytest.param(vm_broken(lambda s: s["steps"].pop(0)), "`canary_vm` is set and no step uses it", id="canary-vm-without-vm-step"),
        pytest.param(vm_broken(lambda s: s["steps"].append({"id": "again", "vm": "up"})), "at most one step may be a vm step", id="two-vm-steps"),
        pytest.param(vm_broken(lambda s: s["steps"].reverse()), "must come before every flows step", id="vm-step-after-a-flows-step"),
        pytest.param(vm_broken(lambda s: s["steps"][0].update(vm="down")), "`vm` to be one of up", id="bad-vm-mode"),
        pytest.param(vm_broken(lambda s: s["steps"][0].update(expect="pass")), "takes no `expect`", id="vm-expect"),
        pytest.param(vm_broken(lambda s: s.update(canary_vm="services")), "`canary_vm` must be a mapping", id="canary-vm-not-a-mapping"),
        pytest.param(vm_broken(lambda s: s["canary_vm"].update(colour="red")), "`canary_vm` has the unknown key `colour`", id="canary-vm-unknown-key"),
        pytest.param(vm_broken(lambda s: s["canary_vm"].pop("zone")), "`canary_vm.zone` must name a zone", id="canary-vm-without-zone"),
        pytest.param(vm_broken(lambda s: s["canary_vm"].update(zone="nowhere")), "the zone `nowhere` is not in the flow list", id="canary-vm-unknown-zone"),
        pytest.param(
            vm_broken(lambda s: s.update(gateway={"vlans": [30, 40]})),
            "`services` is on VLAN 20, which `gateway.vlans` does not carry",
            id="zone-vlan-not-seeded",
        ),
    ],
)
def test_a_mistake_in_a_canary_vm_spec_is_refused_with_its_reason(data, message):
    with pytest.raises(SpecError, match=message):
        parse_spec(data)


def test_a_zone_the_gateways_play_does_not_have_is_refused(tmp_path):
    flows = yaml.safe_load((RUNS.parents[3] / "tools" / "network_checks" / "flows.yaml").read_text())
    flows["zones"]["lab"] = {"subnet": "192.168.90.0/24", "canary": "192.168.90.8"}
    path = tmp_path / "flows.yaml"
    path.write_text(yaml.safe_dump(flows))
    with pytest.raises(SpecError, match="the gateway's play has no zone `lab`"):
        parse_spec(vm_broken(lambda s: s["canary_vm"].update(zone="lab")), path)
