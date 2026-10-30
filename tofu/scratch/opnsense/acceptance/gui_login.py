#!/usr/bin/env python3
"""Check what the gateway's GUI login accepts, from the operator host through the tunnel.

    gui_login.py --credentials FILE [--host OPNsense.internal] [--port 8443] [--ca FILE] [--scheme https]

The credentials file holds root's password (opnsense_root_password) and its one-time password seed
(opnsense_root_otp_seed). The GUI takes the six-digit code in front of the password. Each attempt is a
fresh session: the login page is fetched for its hidden fields and cookie, the form is posted, and a
redirect means the login was accepted while the login form coming back means it was refused. Prints one
LOGIN line per check and exits 1 when any check fails. Standard library only.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import http.cookiejar
import re
import ssl
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def totp(seed: str, at: float | None = None, digits: int = 6, step: int = 30) -> str:
    key = base64.b32decode(seed.upper() + "=" * (-len(seed) % 8))
    counter = int((time.time() if at is None else at) // step)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    return f"{(struct.unpack('>I', digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 10**digits:0{digits}d}"


def read_credential(text: str, name: str) -> str | None:
    m = re.search(rf'(?m)^\s*{name}\s*=\s*"([^"]*)"', text)
    return m[1] if m else None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Leave a redirect unfollowed: its status is what says the login was accepted."""

    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


def hidden_fields(html: str) -> dict[str, str]:
    fields = {}
    for tag in re.findall(r"<input\b[^>]*>", html, re.IGNORECASE):
        if re.search(r"""type\s*=\s*["']hidden["']""", tag, re.IGNORECASE):
            name = re.search(r"""name\s*=\s*["']([^"']*)["']""", tag, re.IGNORECASE)
            value = re.search(r"""value\s*=\s*["']([^"']*)["']""", tag, re.IGNORECASE)
            if name:
                fields[name[1]] = value[1] if value else ""
    return fields


def attempt(base: str, context: ssl.SSLContext | None, user: str, password: str) -> tuple[str, str]:
    """('accepted' | 'refused' | 'unexpected ...', the server's Date header)."""
    jar = http.cookiejar.CookieJar()
    handlers: list[urllib.request.BaseHandler] = [urllib.request.HTTPCookieProcessor(jar), NoRedirect()]
    if context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=context))
    opener = urllib.request.build_opener(*handlers)
    with opener.open(base + "/", timeout=20) as page:
        html = page.read().decode("utf-8", "replace")
        date = page.headers.get("Date", "")
    form = {**hidden_fields(html), "usernamefld": user, "passwordfld": password, "login": "1"}
    request = urllib.request.Request(base + "/", data=urllib.parse.urlencode(form).encode(), method="POST")  # noqa: S310 - base is the tunnel's http(s) URL
    try:
        with opener.open(request, timeout=20) as reply:
            body = reply.read().decode("utf-8", "replace")
            return ("refused" if "usernamefld" in body else f"unexpected {reply.status} without the login form"), date
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303):
            return "accepted", date
        return f"unexpected {e.code}", date


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--credentials", required=True)
    ap.add_argument("--host", default="OPNsense.internal")
    ap.add_argument("--port", type=int, default=8443)
    ap.add_argument("--ca")
    ap.add_argument("--scheme", choices=["https", "http"], default="https")
    a = ap.parse_args(argv)
    with open(a.credentials) as fh:
        text = fh.read()
    password, seed = read_credential(text, "opnsense_root_password"), read_credential(text, "opnsense_root_otp_seed")
    if not password or not seed:
        print("LOGIN setup: FAIL (the credentials file holds no root password or no OTP seed)")
        return 1
    base = f"{a.scheme}://{a.host}:{a.port}"
    context = ssl.create_default_context(cafile=a.ca) if a.scheme == "https" else None

    now = time.time()
    valid = {totp(seed, now + shift) for shift in (-30, 0, 30)}
    wrong = next(f"{n:06d}" for n in range(123456, 10**6) if f"{n:06d}" not in valid)
    checks = [
        ("the password alone is refused", password, "refused"),
        ("the code in front of the password is accepted", totp(seed, now) + password, "accepted"),
        ("a wrong code in front of the password is refused", wrong + password, "refused"),
        ("the code after the password is refused", password + totp(seed, now), "refused"),
    ]
    failed = 0
    for name, secret, expect in checks:
        try:
            got, date = attempt(base, context, "root", secret)
        except OSError as e:  # URLError is an OSError
            got, date = f"unreachable ({e})", ""
        ok = got == expect
        failed += not ok
        here = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())
        extra = "" if ok else f" (expected {expect}, got {got}; the gateway's clock says {date or 'nothing'}, this host's {here})"
        print(f"LOGIN {name}: {'PASS' if ok else 'FAIL'}{extra}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
