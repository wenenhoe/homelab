"""A stand-in for the OPNsense VM's serial socket, with the prompts of the 26.1.6 sources.

It prints what a first boot of the pre-installed image prints (the importer's
key window and device prompt, then the console's login, menu and shell),
echoes typed characters like a tty, and answers the few commands the driver
types. Faults reach the driver's failure paths:

  wrongdisk    the importer finds no such disk and bootstraps a default configuration
  noimporter   the first boot never offers the importer
  badpw        the console refuses the seed's root password
  shellstart   after the import the console is inside a root shell, not at a login
  nocert       the web GUI never creates its certificate
  nobanner     the console banner prints no fingerprint
"""

from __future__ import annotations

import contextlib
import hashlib
import re
import socket
import ssl
import threading
import time
from pathlib import Path

MENU = "\n  0) Logout                              7) Ping host\n  8) Shell\n\n"
CERT_PATH = "/usr/local/etc/lighttpd_webgui/cert.pem"


def fingerprint_banner(pem: str) -> str:
    digest = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest().upper()
    pairs = [digest[i : i + 2] for i in range(0, 64, 2)]
    return " HTTPS: SHA256 " + " ".join(pairs[:16]) + "\r\n               " + " ".join(pairs[16:]) + "\r\n"


class FakeConsole:
    def __init__(self, path: Path, cert_pem: str, *, banner_pem=None, seed_password, disk="da1", fault=None, importer_wait=1.0, boot_delay=0.05):
        """`banner_pem` is the certificate whose fingerprint the banner prints; the one the GUI serves when omitted."""
        self.cert_pem = cert_pem
        self.banner_pem = banner_pem or cert_pem
        self.disk = disk
        self.seed_password = seed_password
        self.fault = fault
        self.importer_wait = importer_wait
        self.boot_delay = boot_delay
        self.typed_at_password = []
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.bind(str(path))
        self._srv.listen(1)
        self._conn = None
        self._lock = threading.Lock()
        self._key = threading.Event()
        self._dev = threading.Event()
        self._phase = "booting"
        self._seeded = False
        self._shell = None
        self._rc = 0
        self._line = ""
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def close(self):
        for sock in (self._conn, self._srv):
            if sock:
                sock.close()
        self._thread.join(timeout=5)

    def _out(self, text):
        # The driver may hang up while the boot thread still has output to print.
        with self._lock, contextlib.suppress(OSError):
            self._conn.sendall(text.encode())

    def _banner(self):
        if self.fault == "nobanner":
            return ""
        return fingerprint_banner(self.banner_pem)

    def _menu(self):
        self._phase = "menu"
        self._out("\x1b[2J*** OPNsense.internal: OPNsense 26.1.6 ***\r\n\r\n" + self._banner() + MENU.replace("\n", "\r\n") + "Enter an option: ")

    def _login_prompt(self):
        self._phase = "login"
        self._out("\r\nOPNsense.internal login: ")

    def _boot(self):
        time.sleep(self.boot_delay)
        if self.fault != "noimporter":
            self._phase = "importer_key"
            self._out("Press any key to start the configuration importer: .")
            if self._key.wait(self.importer_wait):
                self._phase = "importer_dev"
                self._out("\r\n\r\nSelect device to import from (e.g. ada0) or leave blank to exit: ")
                self._dev.wait(30)
                if self._seeded:
                    self._out(f"Starting import for partition '/dev/{self.disk}s1'.\r\n\r\nRestoring config.xml...done.\r\n")
                else:
                    self._out("No known partition layout was found.\r\nBootstrapping config.xml...done.\r\n")
            else:
                self._out("\r\nBootstrapping config.xml...done.\r\n")
        self._seeded = self._seeded or self.fault == "noimporter"
        self._out("Configuring system... done.\r\n")
        if self.fault == "shellstart":
            self._phase = "shell"
            self._shell = "sh"
            self._out("# ")
            return
        self._login_prompt()

    def _expand(self, text):
        text = re.sub(r"\$\(\((\d+)\*(\d+)\)\)", lambda m: str(int(m[1]) * int(m[2])), text)
        return text.replace("$?", str(self._rc))

    def _run(self, line):
        for cmd in (c.strip() for c in line.split(";") if c.strip()):
            if cmd.startswith("echo "):
                text = self._expand(cmd[5:]) + "\r\n"
                # A reader that stops at the first chunk would cut the last value short.
                self._out(text[:-3])
                time.sleep(0.02)
                self._out(text[-3:])
                self._rc = 0
            elif cmd == f"test -s {CERT_PATH}":
                self._rc = 1 if self.fault == "nocert" else 0
            elif cmd == f"cat {CERT_PATH}" and self.fault != "nocert":
                self._out(self.cert_pem.replace("\n", "\r\n"))

    def _serve(self):
        try:
            self._conn, _ = self._srv.accept()
        except OSError:
            return
        threading.Thread(target=self._boot, daemon=True).start()
        while True:
            try:
                data = self._conn.recv(4096)
            except OSError:
                return
            if not data:
                return
            for ch in data.decode(errors="replace"):
                self._on_char(ch)

    def _on_char(self, ch):
        if self._phase == "importer_key":
            self._key.set()
            return
        if self._phase == "importer_dev":
            if ch == "\r":
                self._out("\r\n")
                self._seeded = self._line == self.disk and self.fault != "wrongdisk"
                self._line = ""
                self._phase = "booting"
                self._dev.set()
            else:
                self._line += ch
                self._out(ch)
            return
        if self._phase == "booting":
            return
        if ch == "\x03":
            self._line = ""
            return
        if self._phase == "password" and ch != "\r":
            self._line += ch
            self.typed_at_password.append(ch)
            return
        if ch != "\r":
            self._line += ch
            self._out(ch)
            return
        self._out("\r\n")
        line, self._line = self._line, ""
        {"login": self._on_login, "password": self._on_password, "menu": self._on_menu, "shell": self._on_shell}[self._phase](line)

    def _on_login(self, line):
        if line == "root":
            self._phase = "password"
            self._out("Password:")
        else:
            self._login_prompt()

    def _on_password(self, line):
        good = "wrong" if self.fault == "badpw" else self.seed_password
        if line == good and self._seeded:
            self._menu()
        else:
            self._out("Login incorrect")
            self._login_prompt()

    def _on_menu(self, line):
        if line == "8":
            self._phase = "shell"
            self._shell = "csh"
            self._out("# ")
        else:
            self._menu()

    def _on_shell(self, line):
        if line == "sh":
            self._shell = "sh"
        elif line == "exit":
            # Leaving sh returns to csh, and leaving csh returns to the menu.
            if self._shell == "sh":
                self._shell = "csh"
            else:
                self._menu()
                return
        else:
            self._run(line)
        self._out("# ")
