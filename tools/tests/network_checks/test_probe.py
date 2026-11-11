"""Tests for network_checks.probe against local listeners that stand in for a canary's destinations.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import json
import re
import socket
import struct
import subprocess
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from network_checks import probe

TIMEOUT = 0.5


def spec(kind: str, port: int | None = None, **changes: object) -> dict[str, object]:
    base = {"id": "flow", "kind": kind, "address": "127.0.0.1", "port": port, "protocol": None, "query": None, "timeout": TIMEOUT}
    return {**base, **changes}


@contextmanager
def udp_server(reply: Callable[[bytes], bytes | None]) -> Iterator[int]:
    """A UDP socket on a free port that answers each datagram with `reply(datagram)`, or stays silent when that is none."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(0.1)
    stop = threading.Event()

    def serve() -> None:
        while not stop.is_set():
            try:
                data, peer = sock.recvfrom(4096)
            except TimeoutError:
                continue
            answer = reply(data)
            if answer is not None:
                sock.sendto(answer, peer)

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        yield sock.getsockname()[1]
    finally:
        stop.set()
        thread.join()
        sock.close()


def dns_answer(query: bytes, rcode: int = 0) -> bytes:
    """The query's own bytes with the response flag and `rcode` set, as a resolver answers."""
    return query[:2] + struct.pack(">H", 0x8180 | rcode) + query[4:]


@contextmanager
def tcp_dns_server() -> Iterator[int]:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()

    def serve() -> None:
        connection, _ = server.accept()
        with connection:
            length = struct.unpack(">H", connection.recv(2))[0]
            query = connection.recv(length)
            answer = dns_answer(query)
            connection.sendall(struct.pack(">H", len(answer)) + answer)

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        yield server.getsockname()[1]
    finally:
        thread.join()
        server.close()


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


class TestConnect:
    def test_an_open_port_is_ok(self, listening_port):
        result = probe.probe(spec("connect", listening_port, protocol="tcp"))

        assert (result["id"], result["status"]) == ("flow", probe.OK)

    def test_a_refused_connection_is_failed(self, closed_port):
        result = probe.probe(spec("connect", closed_port, protocol="tcp"))

        assert result["status"] == probe.FAILED
        assert "ConnectionRefusedError" in result["detail"]

    def test_an_address_that_cannot_be_reached_is_failed(self):
        result = probe.probe(spec("connect", 9, protocol="tcp", address="256.0.0.1"))

        assert result["status"] == probe.FAILED


class TestDns:
    def test_a_udp_resolver_that_answers_is_ok(self):
        with udp_server(dns_answer) as port:
            result = probe.probe(spec("dns", port, protocol="udp", query="host.lab"))

        assert (result["status"], result["detail"]) == (probe.OK, "answered with response code 0")

    def test_a_resolver_that_says_the_name_does_not_exist_has_answered(self):
        with udp_server(lambda query: dns_answer(query, rcode=3)) as port:
            result = probe.probe(spec("dns", port, protocol="udp", query="absent.lab"))

        assert (result["status"], result["detail"]) == (probe.OK, "answered with response code 3")

    def test_a_tcp_resolver_that_answers_is_ok(self):
        with tcp_dns_server() as port:
            result = probe.probe(spec("dns", port, protocol="tcp", query="host.lab"))

        assert result["status"] == probe.OK

    def test_a_silent_resolver_is_failed(self):
        with udp_server(lambda query: None) as port:
            result = probe.probe(spec("dns", port, protocol="udp", query="host.lab"))

        assert result["status"] == probe.FAILED

    def test_a_reply_to_another_query_is_failed(self):
        with udp_server(lambda query: struct.pack(">H", (struct.unpack(">H", query[:2])[0] + 1) % 65536) + dns_answer(query)[2:]) as port:
            result = probe.probe(spec("dns", port, protocol="udp", query="host.lab"))

        assert (result["status"], result["detail"]) == (probe.FAILED, "the reply did not answer the query")

    def test_the_query_names_the_name_asked_for(self):
        asked = []

        def reply(query: bytes) -> bytes:
            asked.append(query[12:])
            return dns_answer(query)

        with udp_server(reply) as port:
            probe.probe(spec("dns", port, protocol="udp", query="host.lab"))

        assert asked == [b"\x04host\x03lab\x00\x00\x01\x00\x01"]


class TestNtp:
    def test_a_server_response_is_ok(self):
        with udp_server(lambda packet: b"\x24" + 47 * b"\x00") as port:
            result = probe.probe(spec("ntp", port, protocol="udp"))

        assert result["status"] == probe.OK

    def test_an_echo_of_the_request_is_failed(self):
        with udp_server(lambda packet: packet) as port:
            result = probe.probe(spec("ntp", port, protocol="udp"))

        assert (result["status"], result["detail"]) == (probe.FAILED, "the reply was not an NTP server response")

    def test_a_silent_server_is_failed(self):
        with udp_server(lambda packet: None) as port:
            result = probe.probe(spec("ntp", port, protocol="udp"))

        assert result["status"] == probe.FAILED


class TestPing:
    def run_ping(self, returncode: int) -> dict[str, str]:
        done = subprocess.CompletedProcess(args=[], returncode=returncode, stdout="", stderr="")
        with patch.object(probe.subprocess, "run", autospec=True, return_value=done) as run:
            result = probe.probe(spec("ping", address="10.2.0.1", timeout=3.0))
        run.assert_called_once()
        assert run.call_args.args[0] == ["ping", "-c", "1", "-W", "3", "10.2.0.1"]
        return result

    def test_a_reply_is_ok(self):
        assert self.run_ping(0)["status"] == probe.OK

    def test_no_reply_is_failed(self):
        assert self.run_ping(1)["status"] == probe.FAILED

    def test_a_ping_that_never_returns_is_failed(self):
        with patch.object(probe.subprocess, "run", autospec=True, side_effect=subprocess.TimeoutExpired("ping", 8)):
            result = probe.probe(spec("ping", address="10.2.0.1"))

        assert result["status"] == probe.FAILED

    def test_a_canary_without_ping_cannot_run_the_probe(self):
        with patch.object(probe.subprocess, "run", autospec=True, side_effect=FileNotFoundError("ping")):
            result = probe.probe(spec("ping", address="10.2.0.1"))

        assert (result["status"], result["detail"]) == (probe.ERROR, "ping is not installed on the canary")


def test_an_unknown_kind_cannot_be_run():
    result = probe.probe(spec("telnet", 23))

    assert (result["status"], result["detail"]) == (probe.ERROR, "unknown kind 'telnet'")


def test_a_flow_missing_a_field_cannot_be_run():
    incomplete = spec("connect", 80, protocol="tcp")
    del incomplete["address"]

    result = probe.probe(incomplete)

    assert result["status"] == probe.ERROR
    assert "address" in result["detail"]


def test_main_prints_one_json_result_per_flow(listening_port, closed_port, capsys):
    specs = [spec("connect", listening_port, id="open", protocol="tcp"), spec("connect", closed_port, id="shut", protocol="tcp")]

    code = probe.main(["probe.py", json.dumps(specs)])

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert code == 0
    assert [(line["id"], line["status"]) for line in lines] == [("open", probe.OK), ("shut", probe.FAILED)]


@pytest.mark.parametrize("argv", [pytest.param(["probe.py"], id="no-argument"), pytest.param(["probe.py", "not json"], id="not-json")])
def test_main_reports_an_error_when_it_is_not_given_flows(argv, capsys):
    code = probe.main(argv)

    assert code == 2
    assert json.loads(capsys.readouterr().out)["status"] == probe.ERROR


def test_the_module_is_written_for_the_python_a_canary_has():
    """It runs under the canary's own `python3`, which is older than the 3.14 the repo's formatter targets and so
    cannot read `except A, B:` without parentheses. A formatter that strips them must not reach this file."""
    source = Path(probe.__file__).read_text()

    assert re.search(r"^\s*except\s+[\w.]+\s*,", source, flags=re.MULTILINE) is None
