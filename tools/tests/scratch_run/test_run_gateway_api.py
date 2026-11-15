from __future__ import annotations

import base64
import http.server
import json
import ssl
import subprocess
import threading

import pytest
from scratch_run.gateway_api import INTERFACE_LIST_PATH, NO_ANSWER, get, interface_names, judge_vlans

KEY, SECRET = "key-value-1", "secret-value-1"
TAGS = (20, 30, 40, 50, 60, 70)


def listing(*names: str) -> str:
    return json.dumps({"floating": {"items": [{"value": ""}]}, "groups": {"items": []}, "interfaces": {"items": [{"value": name} for name in names]}})


def certificate(directory):
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes", "-keyout", str(directory / "key.pem"),
            "-out", str(directory / "cert.pem"), "-days", "2", "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    return directory / "cert.pem", directory / "key.pem"


@pytest.fixture(scope="module")
def own_certificate(tmp_path_factory):
    return certificate(tmp_path_factory.mktemp("own"))


@pytest.fixture(scope="module")
def other_certificate(tmp_path_factory):
    return certificate(tmp_path_factory.mktemp("other"))


@pytest.fixture
def gateway(own_certificate):
    """A TLS server with a certificate of its own that answers the interface list to the right key and 401 to any other."""
    seen: list[dict[str, str]] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append({"path": self.path, "authorization": self.headers.get("Authorization", "")})
            good = self.headers.get("Authorization") == "Basic " + base64.b64encode(f"{KEY}:{SECRET}".encode()).decode()
            body = listing("lan", "wan", "opt1").encode() if good else b'{"status": 401}'
            self.send_response(200 if good else 401)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(*map(str, own_certificate))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"https://localhost:{server.server_port}/{INTERFACE_LIST_PATH}", seen
    server.shutdown()
    server.server_close()
    thread.join()


def test_get_sends_the_key_and_secret_as_basic_auth_over_a_certificate_it_trusts(gateway, own_certificate):
    url, seen = gateway
    status, body = get(url, cafile=own_certificate[0], key=KEY, secret=SECRET)
    assert (status, interface_names(body)) == (200, ["lan", "wan", "opt1"])
    assert seen[0]["path"] == f"/{INTERFACE_LIST_PATH}"


def test_get_answers_the_status_and_body_of_a_refusal(gateway, own_certificate):
    status, body = get(gateway[0], cafile=own_certificate[0], key=KEY, secret="wrong")
    assert (status, json.loads(body)) == (401, {"status": 401})


def test_get_does_not_trust_a_certificate_other_than_the_one_given(gateway, other_certificate):
    status, body = get(gateway[0], cafile=other_certificate[0], key=KEY, secret=SECRET)
    assert status == NO_ANSWER
    assert "CERTIFICATE_VERIFY_FAILED" in body
    assert gateway[1] == []


def test_get_does_not_go_through_a_proxy(gateway, own_certificate, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    assert get(gateway[0], cafile=own_certificate[0], key=KEY, secret=SECRET)[0] == 200


def test_get_says_so_when_nothing_is_listening(own_certificate):
    status, body = get("https://127.0.0.1:9/x", cafile=own_certificate[0], key=KEY, secret=SECRET, timeout=5)
    assert status == NO_ANSWER and "Connection refused" in body


def test_get_refuses_a_url_that_is_not_https(own_certificate):
    status, body = get("http://localhost/x", cafile=own_certificate[0], key=KEY, secret=SECRET)
    assert status == NO_ANSWER and "not https" in body


def test_an_error_message_does_not_carry_the_credentials(own_certificate):
    _, body = get("https://127.0.0.1:9/x", cafile=own_certificate[0], key=KEY, secret=SECRET, timeout=5)
    assert KEY not in body and SECRET not in body


@pytest.mark.parametrize(
    ("body", "names"),
    [
        pytest.param(listing("lan", "opt1"), ["lan", "opt1"], id="interfaces"),
        pytest.param("not json", None, id="not-json"),
        pytest.param(json.dumps({"interfaces": {}}), None, id="no-items"),
        pytest.param(json.dumps({"interfaces": {"items": [{"label": "x"}]}}), None, id="item-without-a-value"),
        pytest.param(json.dumps([]), None, id="not-an-object"),
    ],
)
def test_the_interface_names_are_read_from_the_listing_or_not_at_all(body, names):
    assert interface_names(body) == names


@pytest.mark.parametrize(
    ("status", "body", "passed", "says"),
    [
        pytest.param(
            200, listing("lan", "wan", *(f"opt{n}" for n in range(1, 7))), True, "has 6 VLAN interfaces (opt1, opt2, opt3, opt4, opt5, opt6)", id="match"
        ),
        pytest.param(
            200,
            listing("opt6", "wan", "opt1", "lan", "opt2", "opt3", "opt4", "opt5"),
            True,
            "has 6 VLAN interfaces (opt1, opt2, opt3",
            id="any-order-and-sorted",
        ),
        pytest.param(
            200,
            listing("opt1", "opt2", "opt10", "opt3", "opt4", "opt5", "opt6", "opt7", "opt8", "opt9"),
            False,
            "has 10 VLAN interfaces",
            id="more-than-seeded",
        ),
        pytest.param(200, listing("lan", "wan", *(f"opt{n}" for n in range(1, 6))), False, "has 5 VLAN interfaces", id="fewer-than-seeded"),
        pytest.param(200, listing("lan", "wan", "opt1", "opt2", "opt3", "opt4", "opt5", "opt7"), False, "opt1, opt2, opt3, opt4, opt5, opt7", id="a-gap"),
        pytest.param(200, listing("lan", "wan"), False, "has 0 VLAN interfaces (none)", id="none"),
        pytest.param(401, "{}", False, "answered HTTP 401", id="refused"),
        pytest.param(NO_ANSWER, "timed out", False, "gave no answer", id="no-answer"),
        pytest.param(200, "<html>", False, "not in the shape this check reads", id="odd-body"),
    ],
)
def test_the_gateway_has_the_vlan_interfaces_the_seed_was_given_or_the_check_says_what_it_found(status, body, passed, says):
    ok, sentence = judge_vlans(status, body, TAGS)
    assert ok is passed
    assert says in sentence
    if status == 200 and interface_names(body) is not None:
        assert "the spec seeds 6 VLANs (20, 30, 40, 50, 60, 70)" in sentence
