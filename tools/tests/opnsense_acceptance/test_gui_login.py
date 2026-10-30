"""Tests for the GUI login check, run against a stand-in login page that checks the hidden field and cookie like the real page."""

from __future__ import annotations

import http.server
import re
import threading
import urllib.parse
from collections.abc import Callable, Iterator
from pathlib import Path

import gui_login
import pytest

SEED = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
PASSWORD = "root-pw-123"
LOGIN_PAGE = b'<form method="post"><input type="hidden" name="csrf1" value="tok42"/><input name="usernamefld"><input name="passwordfld" type="password"></form>'


def accepts(mode: str, secret: str) -> bool:
    code = gui_login.totp(SEED)
    if mode == "password-only":
        return secret == PASSWORD
    if mode == "any-code":
        return re.fullmatch(r"\d{6}" + PASSWORD, secret) is not None
    if mode == "either-order":
        return secret in (code + PASSWORD, PASSWORD + code)
    return secret == code + PASSWORD


def handler_for(mode: str) -> type[http.server.BaseHTTPRequestHandler]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Set-Cookie", "PHPSESSID=abc; Path=/")
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(LOGIN_PAGE)

        def do_POST(self) -> None:
            form = urllib.parse.parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
            token_ok = form.get("csrf1") == ["tok42"] and "PHPSESSID=abc" in self.headers.get("Cookie", "")
            if token_ok and accepts(mode, form.get("passwordfld", [""])[0]):
                self.send_response(302)
                self.send_header("Location", "/index.php")
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'<form><input name="usernamefld"></form>Wrong username or password.')

    return Handler


@pytest.fixture
def login_page() -> Iterator[Callable[[str], int]]:
    """Start a stand-in login page in the given mode and return its port; every server started is shut down at the end."""
    servers: list[http.server.ThreadingHTTPServer] = []

    def start(mode: str) -> int:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_for(mode))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return server.server_port

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def run_check(tmp_path: Path, port: int, credentials: str) -> int:
    path = tmp_path / "credentials.tfvars"
    path.write_text(credentials)
    return gui_login.main(["--credentials", str(path), "--scheme", "http", "--host", "127.0.0.1", "--port", str(port)])


FULL = f'opnsense_root_password = "{PASSWORD}"\nopnsense_root_otp_seed = "{SEED}"\n'


def test_a_login_that_needs_the_code_in_front_passes_every_check(login_page, tmp_path, capsys):
    status = run_check(tmp_path, login_page("totp"), FULL)

    out = capsys.readouterr().out
    assert status == 0, out
    assert out.count("PASS") == 4


@pytest.mark.parametrize(
    ("mode", "failing"),
    [
        pytest.param(
            "password-only",
            ["the password alone is refused", "the code in front of the password is accepted"],
            id="password-alone",
        ),
        pytest.param("any-code", ["a wrong code in front of the password is refused"], id="any-code"),
        pytest.param("either-order", ["the code after the password is refused"], id="either-order"),
    ],
)
def test_a_login_that_lets_too_much_in_fails_the_checks_it_breaks(login_page, tmp_path, capsys, mode, failing):
    status = run_check(tmp_path, login_page(mode), FULL)

    out = capsys.readouterr().out
    assert status == 1
    assert [line.split(": FAIL")[0].removeprefix("LOGIN ") for line in out.splitlines() if ": FAIL" in line] == failing


def test_an_unreachable_gateway_fails_every_check(tmp_path, capsys):
    status = run_check(tmp_path, 1, FULL)

    out = capsys.readouterr().out
    assert status == 1
    assert out.count("unreachable") == 4


def test_a_file_without_the_seed_stops_before_any_request(tmp_path, capsys):
    status = run_check(tmp_path, 1, f'opnsense_root_password = "{PASSWORD}"\n')

    out = capsys.readouterr().out
    assert status == 1
    assert "no OTP seed" in out
    assert "unreachable" not in out


def test_the_code_matches_the_rfc_6238_vector():
    # RFC 6238 appendix B, SHA-1, 8 digits, seed "12345678901234567890", T = 59 s.
    assert gui_login.totp("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", at=59, digits=8) == "94287082"
