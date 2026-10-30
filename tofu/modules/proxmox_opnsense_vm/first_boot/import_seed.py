#!/usr/bin/env python3
"""Seed a freshly started OPNsense gateway through its serial console.

Run on the Proxmox node right after `qm start`, with the VM's serial socket as
--socket and the seed's root password as the first line of stdin. The image's
first boot offers a short window to press a key at the configuration importer;
the driver answers it with the name of the seed disk, so the importer restores
the seed before any service starts. It then logs in at the console with the
seed's root password and reads the web GUI's certificate off the console, which
is the CA file the Ansible play pins. Every prompt is waited for before it is
answered, because the console has no screen to read. Standard library only.

Writes the raw console transcript, a JSON result and the certificate.

Exit status: 0 done, 2 a prompt did not appear in time (the step is named and
the tail of the transcript printed), 3 the seed did not land, 4 the console
refused the root password, 5 the certificate was not read or does not match the
fingerprint the console banner prints.
"""

import argparse
import contextlib
import hashlib
import json
import os
import re
import select
import socket
import ssl
import sys
import time

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[()][A-Z0-9]|\x1b[=>]")
CERT_PATH = "/usr/local/etc/lighttpd_webgui/cert.pem"
SHELL_PROMPT = r"\n[^\n]*# \Z"


class Timeout(Exception):
    pass


class LoginRefused(Exception):
    pass


class Console:
    def __init__(self, path, log_path, connect_timeout):
        self.t0 = time.monotonic()
        deadline = self.t0 + connect_timeout
        while not os.path.exists(path):
            if time.monotonic() > deadline:
                raise Timeout(f"serial socket {path} did not appear")
            time.sleep(0.2)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self.sock.setblocking(False)
        self.buf = ""
        self.pos = 0
        self.last_rx = time.monotonic()
        self.log = open(log_path, "ab", buffering=0)  # noqa: SIM115 - kept open for the whole run

    def close(self):
        self.sock.close()
        self.log.close()

    def elapsed(self):
        return time.monotonic() - self.t0

    def say(self, msg):
        print(f"t+{self.elapsed():6.1f}s  {msg}", flush=True)

    def _pump(self, wait):
        ready, _, _ = select.select([self.sock], [], [], wait)
        if not ready:
            return
        data = self.sock.recv(65536)
        if not data:
            raise ConnectionError("serial socket closed")
        self.last_rx = time.monotonic()
        self.log.write(data)
        self.buf += ANSI.sub("", data.decode("utf-8", "replace")).replace("\r", "")

    def send(self, text):
        self.sock.setblocking(True)
        self.sock.sendall(text.encode())
        self.sock.setblocking(False)

    def settle(self, quiet, limit=30.0):
        """Take in output until the console has been silent for `quiet` seconds, or `limit` seconds have passed."""
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline and time.monotonic() - self.last_rx < quiet:
            self._pump(0.1)

    def expect(self, pattern, timeout, step, nudge=None, quiet=20.0):
        """Wait for pattern in the output not yet consumed, and consume up to its end.

        With nudge, that text is sent whenever the console has been silent for
        `quiet` seconds. A boot prints something every few seconds, so a nudge
        never lands on the importer's "press any key" prompt, which counts dots.
        """
        rx = re.compile(pattern)
        deadline = time.monotonic() + timeout
        while True:
            m = rx.search(self.buf, self.pos)
            if m:
                self.pos = m.end()
                return m
            now = time.monotonic()
            if now > deadline:
                raise Timeout(f"step '{step}': no match for /{pattern}/ in {timeout:.0f}s\n--- last output ---\n{self.buf[-600:]}\n-------------------")
            if nudge and now - self.last_rx >= quiet:
                self.send(nudge)
                self.last_rx = now
            self._pump(0.2)


def reach_menu(con, user, password, timeout, quiet, label, settle=5.0):
    """Get to the console menu from wherever the console is.

    The console may be at a login prompt, at the menu, or inside a root shell. A
    newline at the menu or at a login prompt only redraws it, so nudging a silent
    console wakes one that printed its prompt before the driver connected. Inside
    a shell, Ctrl-C and `exit` walk back out to the menu. The password is typed at
    a prompt that does not echo, so it is not in the transcript.

    A console whose menu is not password-protected can print a login prompt while it
    starts and then show the menu. A prompt is answered only once the console has been
    silent for `settle` seconds without the menu having appeared.
    """
    for _ in range(6):
        m = con.expect(rf"login: |Enter an option:|{SHELL_PROMPT}", timeout, f"{label}: login, menu or shell", nudge="\x03\r", quiet=quiet)
        if m.group(0).startswith("Enter"):
            return
        if m.group(0).endswith("login: "):
            con.settle(settle)
            menu = re.compile("Enter an option:").search(con.buf, con.pos)
            if menu:
                con.pos = menu.end()
                return
            break
        con.send("\x03exit\r")
    else:
        raise Timeout(f"step '{label}': still in a shell after six exits")
    con.send(f"{user}\r")
    con.expect(r"Password:", 30, f"{label}: password prompt")
    con.send(f"{password}\r")
    m = con.expect(r"Login incorrect|Enter an option:", 60, f"{label}: menu after login")
    if m.group(0).startswith("Login"):
        raise LoginRefused(f"{label}: the console refused {user}'s password")


def read_certificate(con, step_timeout, poll_interval):
    """The GUI certificate as PEM text, or None; the web GUI creates it a little after the console is up."""
    con.send("8\r")
    # csh is the console shell; one syntax from here on, and a marker whose digits only
    # exist once the shell computes them cannot be matched by the tty's echo of the command.
    con.send("sh\r")
    con.send("echo READY_$((6*7))\r")
    con.expect(r"READY_42", step_timeout, "shell")
    for _ in range(20):
        con.send(f"test -s {CERT_PATH}; echo CERTRC=$?\r")
        if con.expect(r"CERTRC=(\d+)\n", step_timeout, "certificate file").group(1) == "0":
            break
        time.sleep(poll_interval)
    con.send(f"echo CERT_START_$((2*3)); cat {CERT_PATH}; echo CERT_END_$((2*3))\r")
    text = con.expect(r"(?s)CERT_START_6\n(.*?)CERT_END_6", step_timeout, "certificate text").group(1)
    pem = re.search(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", text, re.S)
    return pem.group(0) if pem else None


def banner_fingerprint(buf):
    """The SHA-256 the console banner printed for the GUI certificate at the latest login, as lowercase hex."""
    banners = re.findall(r"HTTPS: SHA256 ((?:[0-9A-F]{2} ?)+)\s+((?:[0-9A-F]{2} ?)+)\n", buf)
    return "".join(banners[-1]).replace(" ", "").lower() if banners else None


def write_result(path, res):
    with open(path, "w") as fh:
        json.dump(res, fh, indent=1)


def run(a, password):
    res = {}
    try:
        con = Console(a.socket, a.log, a.connect_timeout)
    except Timeout as e:
        print(e, file=sys.stderr)
        return 2, res
    with contextlib.closing(con):
        return seed_and_read(con, a, password, res)


def seed_and_read(con, a, password, res):
    con.say(f"connected to {a.socket}")
    st = a.step_timeout
    try:
        # The image has no configuration on its first boot, so its importer offers a short
        # window to press a key; the answer is read from the seed disk before any service starts.
        con.expect(r"Press any key to start the configuration importer", a.boot_timeout, "importer prompt on the first boot")
        con.send(" ")
        con.expect(r"Select device to import from[^\n]*: ", st, "importer device prompt")
        con.send(f"{a.seed_disk}\r")
        m = con.expect(r"Restoring config\.xml\.\.\.done\.|No known partition layout[^\n]*|Bootstrapping config\.xml", st, "importer result")
        res["restored"] = m.group(0).startswith("Restoring")
        con.say(f"importer: {m.group(0)}")
        if not res["restored"]:
            res["result"] = "seed did not land"
            return 3, res
        reach_menu(con, "root", password, a.boot_timeout, a.nudge_quiet, "seeded system", a.login_settle)
        res["first_menu_s"] = round(con.elapsed(), 1)
        con.say("logged in with the seed's root password; the console menu is up")
        pem = read_certificate(con, st, a.poll_interval)
        res["cert_sha256"] = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest() if pem else None
        shown = banner_fingerprint(con.buf)
        res["banner_matches_cert"] = None if shown is None or pem is None else shown == res["cert_sha256"]
        if pem is None:
            res["result"] = "certificate not read"
            return 5, res
        if res["banner_matches_cert"] is False:
            res["result"] = "certificate does not match the console banner"
            return 5, res
        with open(a.cert_out, "w") as fh:
            fh.write(pem + "\n")
        con.say(f"read the GUI certificate off the console, sha256 {res['cert_sha256']}")
        res["total_s"] = round(con.elapsed(), 1)
        res["result"] = "done"
        return 0, res
    except LoginRefused as e:
        res.update(result="login refused", detail=str(e))
        return 4, res
    except (Timeout, ConnectionError) as e:
        res.update(result="timeout", detail=str(e).splitlines()[0])
        print(e, file=sys.stderr)
        return 2, res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--socket", required=True, help="/var/run/qemu-server/<vmid>.serial0")
    ap.add_argument("--seed-disk", default="da1", help="device name of the attached seed disk")
    ap.add_argument("--log", default="console.log", help="raw transcript")
    ap.add_argument("--result", default="result.json")
    ap.add_argument("--cert-out", default="gateway-cert.pem", help="where to write the GUI certificate read from the console")
    ap.add_argument("--connect-timeout", type=float, default=60, help="how long to wait for the serial socket to appear")
    ap.add_argument("--boot-timeout", type=float, default=300)
    ap.add_argument("--step-timeout", type=float, default=60)
    ap.add_argument("--nudge-quiet", type=float, default=20, help="send a newline when the console has been silent this many seconds")
    ap.add_argument("--login-settle", type=float, default=5, help="seconds of silence after a login prompt before it is answered, in case the menu follows")
    ap.add_argument("--poll-interval", type=float, default=3, help="seconds between looks for the certificate file")
    a = ap.parse_args(argv)

    password = sys.stdin.readline().rstrip("\n")
    if not password:
        ap.error("the seed's root password must be the first line of stdin")
    code, res = run(a, password)
    write_result(a.result, res)
    print(json.dumps(res, indent=1) if code == 0 else f"{res.get('result', 'no result')}; see the transcript", file=sys.stdout if code == 0 else sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
