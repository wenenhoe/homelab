"""Tests for network_checks.runner: the decision logic on synthetic results, then whole runs through a stand-in ssh.

The stand-in ssh ignores the login and runs the remote command on this machine, so the real probe module is sent on
standard input to a real interpreter and tries real local listeners.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import socket
import sys
import textwrap
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from network_checks import probe, runner
from network_checks.flow_list import FlowList, load_flow_list

CANARIES = {"alpha": "127.0.0.2", "beta": "127.0.0.130"}


def flow(flow_id: str, source: str, port: int, expect: str = "allow", control: str | None = None, tags: list[str] | None = None) -> dict:
    entry = {"id": flow_id, "from": source, "to": {"address": "127.0.0.1", "port": port}, "kind": "connect", "expect": expect}
    if control:
        entry["control"] = control
    if tags:
        entry["tags"] = tags
    return entry


def zones() -> dict:
    return {
        "alpha": {"subnet": "127.0.0.0/25", "canary": CANARIES["alpha"]},
        "beta": {"subnet": "127.0.0.128/25", "canary": CANARIES["beta"]},
    }


@pytest.fixture
def listening_port() -> Iterator[int]:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        yield server.getsockname()[1]


@pytest.fixture
def closed_port() -> int:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        return server.getsockname()[1]


@pytest.fixture
def make_ssh(tmp_path: Path) -> Callable[[str], list[str]]:
    """A stand-in ssh whose body is the given Python; `argv` is what the runner passed, `log` appends to ssh.log."""

    def make(body: str) -> list[str]:
        script = tmp_path / "fake_ssh.py"
        log = tmp_path / "ssh.log"
        script.write_text(f"import os, sys\nargv = sys.argv\nlog = open({str(log)!r}, 'a')\n" + textwrap.dedent(body))
        return [sys.executable, str(script)]

    return make


RUN_LOCALLY = """
log.write(argv[-2] + "\\n")
log.close()
os.execvp("sh", ["sh", "-c", argv[-1]])
"""


@pytest.fixture
def fake_ssh(make_ssh) -> list[str]:
    return make_ssh(RUN_LOCALLY)


@pytest.fixture
def sessions(tmp_path: Path) -> Callable[[], list[str]]:
    def read() -> list[str]:
        log = tmp_path / "ssh.log"
        return log.read_text().splitlines() if log.exists() else []

    return read


def loaded(write_flows, flows: list[dict]) -> FlowList:
    return load_flow_list(write_flows({"zones": zones(), "flows": flows}))


def run(flow_list: FlowList, ssh: list[str], **kwargs) -> dict[str, runner.Outcome]:
    outcomes = runner.execute(flow_list, list(flow_list.flows), "canary", ssh, python=sys.executable, timeout=1.0, **kwargs)
    return {outcome.flow_id: outcome for outcome in outcomes}


class TestSelect:
    @pytest.fixture
    def flow_list(self, write_flows) -> FlowList:
        return loaded(
            write_flows,
            [
                flow("one", "alpha", 1, tags=["smoke"]),
                flow("two", "alpha", 2),
                flow("three", "beta", 3, expect="deny", control="two", tags=["smoke"]),
            ],
        )

    def ids(self, flow_list: FlowList, tags: list[str], ids: list[str]) -> list[str]:
        return [selected.id for selected in runner.select(flow_list, tags, ids)]

    def test_no_selection_runs_every_flow(self, flow_list):
        assert self.ids(flow_list, [], []) == ["one", "two", "three"]

    def test_a_tag_selects_its_flows_and_the_control_of_a_selected_deny(self, flow_list):
        assert self.ids(flow_list, ["smoke"], []) == ["one", "two", "three"]

    def test_a_flow_id_selects_that_flow_alone(self, flow_list):
        assert self.ids(flow_list, [], ["one"]) == ["one"]

    def test_a_deny_brings_its_control_into_the_run(self, flow_list):
        assert self.ids(flow_list, [], ["three"]) == ["two", "three"]

    def test_an_unknown_flow_id_is_refused(self, flow_list):
        with pytest.raises(ValueError, match="no flow has the id missing"):
            runner.select(flow_list, [], ["missing"])


class TestEvaluate:
    @pytest.fixture
    def flows(self, write_flows) -> list:
        return list(loaded(write_flows, [flow("open", "alpha", 1), flow("shut", "beta", 2, expect="deny", control="open")]).flows)

    def verdicts(self, flows, results: dict[str, str], failures: dict[str, str] | None = None) -> dict[str, tuple[bool, str]]:
        shaped = {flow_id: {"id": flow_id, "status": status, "detail": f"{status} detail"} for flow_id, status in results.items()}
        return {outcome.flow_id: (outcome.passed, outcome.message) for outcome in runner.evaluate(flows, shaped, failures or {})}

    def test_an_allow_passes_when_the_attempt_succeeded(self, flows):
        assert self.verdicts(flows, {"open": probe.OK, "shut": probe.FAILED})["open"] == (True, "allowed")

    def test_an_allow_fails_when_the_attempt_failed(self, flows):
        assert self.verdicts(flows, {"open": probe.FAILED, "shut": probe.FAILED})["open"] == (False, "blocked: failed detail")

    def test_a_deny_passes_when_the_attempt_failed_and_its_control_passed(self, flows):
        assert self.verdicts(flows, {"open": probe.OK, "shut": probe.FAILED})["shut"] == (True, "blocked: failed detail")

    def test_a_deny_fails_when_the_attempt_succeeded(self, flows):
        assert self.verdicts(flows, {"open": probe.OK, "shut": probe.OK})["shut"] == (False, "the attempt succeeded")

    def test_a_deny_whose_control_failed_is_failed_even_though_the_attempt_failed(self, flows):
        assert self.verdicts(flows, {"open": probe.FAILED, "shut": probe.FAILED})["shut"] == (False, "its control open failed, so a block is not shown")

    def test_a_deny_whose_control_had_no_result_is_failed(self, flows):
        verdict = self.verdicts(flows, {"shut": probe.FAILED}, {"open": "the session failed"})

        assert verdict["shut"][0] is False
        assert verdict["open"] == (False, "no result: the session failed")

    def test_a_probe_that_could_not_run_fails_an_allow_and_a_deny(self, flows):
        verdicts = self.verdicts(flows, {"open": probe.ERROR, "shut": probe.ERROR})

        assert verdicts["open"] == (False, "the probe could not be run: error detail")
        assert verdicts["shut"] == (False, "the probe could not be run: error detail")

    def test_a_flow_the_canary_never_reported_is_failed(self, flows):
        assert self.verdicts(flows, {"open": probe.OK})["shut"] == (False, "no result: the canary did not report it")


class TestExecute:
    def test_each_kind_of_result_is_decided_through_a_real_session(self, write_flows, fake_ssh, listening_port, closed_port):
        flow_list = loaded(
            write_flows,
            [
                flow("open", "alpha", listening_port),
                flow("shut", "alpha", closed_port),
                flow("blocked", "beta", closed_port, expect="deny", control="open"),
                flow("leak", "beta", listening_port, expect="deny", control="open"),
            ],
        )

        outcomes = run(flow_list, fake_ssh)

        assert {flow_id: outcome.passed for flow_id, outcome in outcomes.items()} == {"open": True, "shut": False, "blocked": True, "leak": False}
        assert outcomes["leak"].message == "the attempt succeeded"

    def test_a_deny_is_failed_when_its_control_cannot_connect(self, write_flows, fake_ssh, closed_port):
        flow_list = loaded(write_flows, [flow("down", "alpha", closed_port), flow("blocked", "beta", closed_port, expect="deny", control="down")])

        outcomes = run(flow_list, fake_ssh)

        assert outcomes["blocked"] == runner.Outcome("blocked", False, "its control down failed, so a block is not shown")

    def test_one_session_runs_per_source_zone_as_the_given_user(self, write_flows, fake_ssh, sessions, listening_port):
        flow_list = loaded(write_flows, [flow("a1", "alpha", listening_port), flow("b1", "beta", listening_port), flow("a2", "alpha", listening_port)])

        run(flow_list, fake_ssh)

        assert sessions() == ["canary@127.0.0.2", "canary@127.0.0.130"]

    def test_a_session_that_fails_fails_its_flows_and_not_the_other_zones(self, write_flows, make_ssh, listening_port):
        ssh = make_ssh(
            """
            if "127.0.0.2" in argv[-2]:
                sys.stderr.write("Permission denied (publickey).")
                sys.exit(255)
            os.execvp("sh", ["sh", "-c", argv[-1]])
            """
        )
        flow_list = loaded(write_flows, [flow("a1", "alpha", listening_port), flow("b1", "beta", listening_port)])

        outcomes = run(flow_list, ssh)

        assert outcomes["b1"].passed is True
        assert outcomes["a1"].passed is False
        assert "failed with status 255: Permission denied (publickey)." in outcomes["a1"].message

    def test_an_ssh_that_is_not_installed_fails_the_flows(self, write_flows, listening_port):
        flow_list = loaded(write_flows, [flow("a1", "alpha", listening_port)])

        outcomes = run(flow_list, ["/nonexistent/ssh"])

        assert outcomes["a1"].passed is False
        assert "can't run /nonexistent/ssh" in outcomes["a1"].message

    def test_a_session_that_prints_something_else_fails_its_flows(self, write_flows, make_ssh, listening_port):
        flow_list = loaded(write_flows, [flow("a1", "alpha", listening_port)])

        outcomes = run(flow_list, make_ssh("print('Welcome to the canary')\n"))

        assert "printed a line that is not a result" in outcomes["a1"].message

    def test_a_session_that_reports_only_some_flows_fails_the_rest(self, write_flows, make_ssh, listening_port):
        ssh = make_ssh("""print('{"id": "a1", "status": "ok", "detail": "connected"}')\n""")
        flow_list = loaded(write_flows, [flow("a1", "alpha", listening_port), flow("a2", "alpha", listening_port)])

        outcomes = run(flow_list, ssh)

        assert (outcomes["a1"].passed, outcomes["a2"].passed) == (True, False)
        assert outcomes["a2"].message == "no result: the canary did not report it"

    def test_a_session_that_never_finishes_is_stopped(self, make_ssh):
        ssh = make_ssh("import time\ntime.sleep(30)\n")

        with pytest.raises(runner.SessionError, match=r"did not finish within 0\.5 seconds"):
            runner.run_session("127.0.0.2", "canary", ssh, sys.executable, [], 0.5)


class TestMain:
    @pytest.fixture
    def args(self, fake_ssh) -> list[str]:
        return ["--ssh-user", "canary", "--ssh-command", " ".join(fake_ssh), "--remote-python", sys.executable]

    @pytest.fixture
    def port(self) -> Iterator[int]:
        """A port with a listener on 127.0.0.1 (zone alpha's subnet) and on 127.0.0.200 (zone beta's)."""
        with socket.socket() as one, socket.socket() as two:
            one.bind(("127.0.0.1", 0))
            one.listen()
            number = one.getsockname()[1]
            two.bind(("127.0.0.200", number))
            two.listen()
            yield number

    def flows_file(self, write_flows, alpha_target: str, beta_target: str, port: int, alpha_port: int | None = None) -> list[str]:
        """A list that holds every rule: one allow flow from each zone to an address in the other."""
        flows = [
            {"id": "a-to-b", "from": "alpha", "to": {"address": alpha_target, "port": alpha_port or port}, "kind": "connect", "expect": "allow"},
            {"id": "b-to-a", "from": "beta", "to": {"address": beta_target, "port": port}, "kind": "connect", "expect": "allow"},
        ]
        return ["--flows", str(write_flows({"zones": zones(), "flows": flows}))]

    def test_exit_zero_and_a_summary_when_every_flow_passes(self, write_flows, args, port, capsys):
        code = runner.main([*args, *self.flows_file(write_flows, "127.0.0.200", "127.0.0.1", port)])

        out = capsys.readouterr().out
        assert code == 0
        assert "PASS a-to-b: allowed" in out
        assert "2 of 2 flows passed" in out

    def test_exit_one_when_one_flow_fails(self, write_flows, args, port, closed_port, capsys):
        code = runner.main([*args, *self.flows_file(write_flows, "127.0.0.200", "127.0.0.1", port, alpha_port=closed_port)])

        out = capsys.readouterr().out
        assert code == 1
        assert "FAIL a-to-b: blocked:" in out
        assert "1 of 2 flows passed" in out

    def test_a_flow_list_that_breaks_a_rule_is_not_run(self, write_flows, args, sessions, port, capsys):
        flows = [{"id": "a-to-b", "from": "alpha", "to": {"address": "127.0.0.200", "port": port}, "kind": "connect", "expect": "allow"}]

        code = runner.main([*args, "--flows", str(write_flows({"zones": zones(), "flows": flows}))])

        assert code == 2
        assert "[pair-covered]" in capsys.readouterr().err
        assert sessions() == []

    def test_a_flow_list_the_loader_refuses_is_not_run(self, write_flows, args, capsys):
        code = runner.main([*args, "--flows", str(write_flows("- not a mapping\n"))])

        assert code == 2
        assert "must be a mapping" in capsys.readouterr().err

    def test_an_empty_selection_is_refused_and_not_passed(self, args, capsys):
        code = runner.main(args)

        assert code == 2
        assert "nothing was shown" in capsys.readouterr().err

    def test_an_unknown_flow_id_is_refused(self, write_flows, args, port, capsys):
        code = runner.main([*args, *self.flows_file(write_flows, "127.0.0.200", "127.0.0.1", port), "--flow", "missing"])

        assert code == 2
        assert "no flow has the id missing" in capsys.readouterr().err

    def test_a_tag_runs_only_the_tagged_flows(self, write_flows, args, sessions, port, capsys):
        flows = [
            {"id": "a-to-b", "from": "alpha", "to": {"address": "127.0.0.200", "port": port}, "kind": "connect", "expect": "allow", "tags": ["smoke"]},
            {"id": "b-to-a", "from": "beta", "to": {"address": "127.0.0.1", "port": port}, "kind": "connect", "expect": "allow"},
        ]

        code = runner.main([*args, "--flows", str(write_flows({"zones": zones(), "flows": flows})), "--tag", "smoke"])

        assert code == 0
        assert "1 of 1 flows passed" in capsys.readouterr().out
        assert sessions() == ["canary@127.0.0.2"]
