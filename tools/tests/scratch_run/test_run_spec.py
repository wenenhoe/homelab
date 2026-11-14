from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml
from conftest import RUNS
from scratch_run.spec import SpecError, load_spec, parse_spec

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
    apply, check, services, block = spec.steps
    assert (spec.vlans, spec.block_rule.port) == ((20, 70), 53)
    assert (apply.expect, check.expect, services.expect, block.expect) == ("ok", "unchanged", "fail", "")
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
        pytest.param(broken(lambda s: s["steps"].pop()), "no step uses it", id="rule-without-block"),
        pytest.param(broken(lambda s: s["steps"][1].update(id="apply")), "`apply` is used twice", id="repeated-step-id"),
        pytest.param(broken(lambda s: s["steps"][0].update(flows={"tags": ["x"]})), "exactly one of play, flows, block", id="two-kinds"),
        pytest.param(broken(lambda s: s["steps"][0].update(play="destroy")), "one of apply, check", id="bad-play-mode"),
        pytest.param(broken(lambda s: s["steps"][0].update(expect="pass")), "one of ok, unchanged, changed", id="wrong-play-expect"),
        pytest.param(broken(lambda s: s["steps"][3].update(expect="ok")), "takes no `expect`", id="block-expect"),
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
