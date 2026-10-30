"""Tests for the API key scope check, run against a stand-in API whose key holds a set of path prefixes."""

from __future__ import annotations

import http.server
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import api_scope
import pytest

NARROW = [path for _, path in api_scope.ALLOWED]


def handler_for(prefixes: list[str], key_ok: bool) -> type[http.server.BaseHTTPRequestHandler]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def handle_any(self) -> None:
            if self.command == "POST":
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
            path = self.path.lstrip("/")
            if not key_ok:
                self.send_response(401)
            elif any(path.startswith(p) for p in prefixes):
                self.send_response(200)
            else:
                self.send_response(403)
            self.end_headers()

        do_GET = do_POST = handle_any

    return Handler


@pytest.fixture
def api() -> Iterator[Callable[..., int]]:
    """Start a stand-in API whose key may reach the given path prefixes and return its port; every server started is shut down at the end."""
    servers: list[http.server.ThreadingHTTPServer] = []

    def start(prefixes: list[str], key_ok: bool = True) -> int:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_for(prefixes, key_ok))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return server.server_port

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def run_check(tmp_path: Path, port: int) -> int:
    path = tmp_path / "credentials.tfvars"
    path.write_text('opnsense_api_key = "k"\nopnsense_api_secret = "s"\n')
    return api_scope.main(["--credentials", str(path), "--scheme", "http", "--host", "127.0.0.1", "--port", str(port)])


def test_a_key_limited_to_the_calls_passes_every_check(api, tmp_path, capsys):
    status = run_check(tmp_path, api(NARROW))

    out = capsys.readouterr().out
    assert status == 0, out
    assert out.count("PASS") == len(api_scope.ALLOWED) + len(api_scope.REFUSED)


def test_a_key_that_may_do_everything_fails_the_refused_calls(api, tmp_path, capsys):
    status = run_check(tmp_path, api(["api/"]))

    out = capsys.readouterr().out
    assert status == 1
    assert out.count("FAIL") == len(api_scope.REFUSED)
    assert "API GET api/auth/user/search: FAIL (expected 403, got 200)" in out


def test_a_key_missing_a_privilege_the_play_needs_fails_that_call_only(api, tmp_path, capsys):
    status = run_check(tmp_path, api([p for p in NARROW if "filter" not in p]))

    out = capsys.readouterr().out
    assert status == 1
    assert out.count("FAIL") == 1
    assert "API GET api/firewall/filter/get: FAIL (expected 200, got 403)" in out


def test_a_refused_key_is_not_taken_for_a_missing_privilege(api, tmp_path, capsys):
    status = run_check(tmp_path, api(NARROW, key_ok=False))

    out = capsys.readouterr().out
    assert status == 1
    assert "got 401" in out
    assert out.count("FAIL") == len(api_scope.ALLOWED) + len(api_scope.REFUSED)


def test_a_file_without_the_key_stops_before_any_request(tmp_path, capsys):
    path = tmp_path / "credentials.tfvars"
    path.write_text('opnsense_api_secret = "s"\n')

    status = api_scope.main(["--credentials", str(path), "--scheme", "http", "--port", "1"])

    assert status == 1
    assert "no API key" in capsys.readouterr().out
