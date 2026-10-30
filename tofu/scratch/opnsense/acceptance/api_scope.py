#!/usr/bin/env python3
"""Check what the seeded API key may and may not ask the gateway for, through the tunnel.

    api_scope.py --credentials FILE [--host OPNsense.internal] [--port 8443] [--ca FILE] [--scheme https]

The calls named under ALLOWED are ones the play and the scratch gateway's update make, read-only ones among
them; each must be answered with 200. The calls under REFUSED belong to privileges the key must not hold,
and each must be answered with 403 (the key is good, the privilege is missing). Prints one API line per
check and exits 1 when any check fails. Standard library only.
"""

from __future__ import annotations

import argparse
import base64
import re
import ssl
import sys
import urllib.error
import urllib.request

ALLOWED = [
    ("GET", "api/diagnostics/system/system_information"),
    ("GET", "api/firewall/filter/get"),
    ("GET", "api/firewall/alias/get"),
    ("GET", "api/kea/dhcpv4/get"),
    ("GET", "api/dnsmasq/settings/get"),
    ("GET", "api/unbound/settings/get"),
    ("POST", "api/core/firmware/status"),
]
REFUSED = [
    ("GET", "api/auth/user/search"),
    ("GET", "api/firewall/source_nat/get"),
    ("GET", "api/core/service/search"),
]


def read_credential(text: str, name: str) -> str | None:
    m = re.search(rf'(?m)^\s*{name}\s*=\s*"([^"]*)"', text)
    return m[1] if m else None


def status(base: str, context: ssl.SSLContext | None, key: str, secret: str, method: str, path: str) -> int | None:
    token = base64.b64encode(f"{key}:{secret}".encode()).decode()
    request = urllib.request.Request(  # noqa: S310 - base is the tunnel's http(s) URL
        f"{base}/{path}", data=b"" if method == "POST" else None, method=method, headers={"Authorization": f"Basic {token}"}
    )
    try:
        with urllib.request.urlopen(request, context=context, timeout=60) as reply:  # noqa: S310
            return reply.status
    except urllib.error.HTTPError as e:
        return e.code
    except OSError:  # URLError is an OSError
        return None


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
    key, secret = read_credential(text, "opnsense_api_key"), read_credential(text, "opnsense_api_secret")
    if not key or not secret:
        print("API setup: FAIL (the credentials file holds no API key or secret)")
        return 1
    base = f"{a.scheme}://{a.host}:{a.port}"
    context = ssl.create_default_context(cafile=a.ca) if a.scheme == "https" else None
    failed = 0
    for expect, calls in ((200, ALLOWED), (403, REFUSED)):
        for method, path in calls:
            got = status(base, context, key, secret, method, path)
            ok = got == expect
            failed += not ok
            print(f"API {method} {path}: {'PASS' if ok else 'FAIL'} (expected {expect}, got {got})", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
