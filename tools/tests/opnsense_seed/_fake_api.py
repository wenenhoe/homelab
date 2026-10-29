"""A stand-in for the gateway's HTTPS API, for testing update_gateway.sh offline.

Serves only what the script calls, with the response shapes read from the 26.1.6 source
(FirmwareController). It is not a model of the gateway.

Faults: nomirror (the firmware status is an error), latest-differs (the update lands past
the pin), noreboot (the update job ends with done, not a reboot), stuck (the update never
ends), badversion (the version is unchanged after the update), keylost (the key is refused
after the update), authopen (a wrong secret is accepted after the update).
"""

from __future__ import annotations

import base64
import json
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeApi:
    def __init__(self, cert: str, key: str, creds: str, *, fault: str = "", want: str = "26.1.11", version: str = "26.1.6_2"):
        self.fault = fault
        self.calls: list[str] = []
        self.creds = creds
        self.latest = "26.1.12" if fault == "latest-differs" else want
        self.state = {"version": version, "job_done": 0.0, "job_kind": "", "down_until": 0.0, "updated": False, "last_done": "", "reboot_at": None}
        self.lock = threading.Lock()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> FakeApi:
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()

    def _handler(self):
        api = self
        auth = "Basic " + base64.b64encode(self.creds.encode()).decode()

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *args):
                pass

            def reply(self, body, code=200):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def handle_any(self, method):
                api.calls.append(f"{method} {self.path}")
                state, fault, now = api.state, api.fault, time.monotonic()
                with api.lock:
                    if state["reboot_at"] and now >= state["reboot_at"]:
                        state.update(reboot_at=None, last_done="", down_until=now + 1.5)
                if now < state["down_until"]:
                    self.close_connection = True
                    return  # an empty reply, as a web server that is restarting gives
                if fault == "keylost" and state["updated"]:
                    return self.reply({"status": 401}, 401)
                if self.headers.get("Authorization") != auth and not (fault == "authopen" and state["updated"]):
                    return self.reply({"status": 401}, 401)
                path = self.path.split("?")[0].removeprefix("/api/")
                with api.lock:
                    if state["job_kind"] and now >= state["job_done"] and state["job_kind"] != "stuck":
                        state.update(last_done=state["job_kind"], job_kind="")
                        if fault != "badversion":
                            state["version"] = api.latest + "_10"
                        state["updated"] = True
                        if fault != "noreboot":
                            state.update(last_done="reboot", reboot_at=now + 0.5)
                    return self.route(method, path, now)

            def route(self, method, path, now):
                state, fault = api.state, api.fault
                if path == "diagnostics/system/systemInformation":
                    return self.reply({"name": "OPNsense", "versions": [state["version"]]})
                if path == "core/firmware/status" and method == "POST":
                    if fault == "nomirror":
                        return self.reply({"status": "error", "status_msg": "Could not connect to the mirror."})
                    behind = not state["version"].startswith(api.latest)
                    packages = [{"name": "opnsense", "current_version": state["version"], "new_version": api.latest + "_10"}] if behind else []
                    return self.reply(
                        {
                            "status": "update" if behind else "none",
                            "status_msg": "There are updates." if behind else "No updates.",
                            "upgrade_packages": packages,
                            "product": {"product_version": state["version"], "product_latest": "26.1.7"},
                        }
                    )
                if path == "core/firmware/update" and method == "POST":
                    state.update(job_kind="stuck" if fault == "stuck" else "update", job_done=now + 1.0, last_done="")
                    return self.reply({"status": "ok", "msg_uuid": "1"})
                if path == "core/firmware/upgradestatus":
                    if state["last_done"] == "reboot":
                        return self.reply({"status": "reboot", "log": "working\n***REBOOT***\n"})
                    if state["job_kind"]:
                        return self.reply({"status": "running", "log": "working\n"})
                    if state["last_done"]:
                        return self.reply({"status": "done", "log": "working\n***DONE***\n"})
                    return self.reply({"status": "error", "log": ""})
                return self.reply({"status": 404}, 404)

            def do_GET(self):
                self.handle_any("GET")

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(length)
                self.handle_any("POST")

        return Handler
