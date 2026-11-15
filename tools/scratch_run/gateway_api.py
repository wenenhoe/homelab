"""One read of the scratch gateway's API, and the judgement of what it says about the VLANs.

The seeded API user holds the least privilege the play needs, and `api/interfaces/vlan_settings/*` is not in it, so the
tags themselves cannot be read. The filter privilege does cover `api/firewall/filter/get_interface_list`, which names
every interface the gateway has. The seed gives each VLAN an interface `opt1`, `opt2`, ... in the order of its list, so
a gateway built with N VLANs has exactly the interfaces `opt1` to `optN`. That shows the seed took the VLAN list the
spec set; it does not show which tag each interface carries.
"""

from __future__ import annotations

import base64
import http.client
import json
import re
import ssl
import urllib.error
import urllib.request
from pathlib import Path

INTERFACE_LIST_PATH = "api/firewall/filter/get_interface_list"
OPTIONAL_INTERFACE_RE = re.compile(r"opt[0-9]+")
NO_ANSWER = 0  # the "HTTP status" of a request that got no HTTP answer at all


def get(url: str, *, cafile: Path, key: str, secret: str, timeout: int = 30) -> tuple[int, str]:
    """GET `url` over TLS that trusts only `cafile`, with no proxy; answer (HTTP status, body), or (0, the error)."""
    if not url.startswith("https://"):
        return NO_ANSWER, f"refusing a URL that is not https: {url}\n"
    context = ssl.create_default_context(cafile=str(cafile))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
    token = base64.b64encode(f"{key}:{secret}".encode()).decode()
    request = urllib.request.Request(url, headers={"Authorization": f"Basic {token}", "Accept": "application/json"})  # noqa: S310 - https only, checked above
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, response.read().decode(errors="replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode(errors="replace")
    except (OSError, http.client.HTTPException, ValueError) as error:  # a refused connection, a timeout and a failed TLS handshake are OSError
        return NO_ANSWER, f"{type(error).__name__}: {error}\n"


def interface_names(body: str) -> list[str] | None:
    """The interface keys the gateway's interface list names, or None when the body is not that list."""
    try:
        sections = json.loads(body)
        items = sections["interfaces"]["items"]
        return [item["value"] for item in items if isinstance(item["value"], str)]
    except ValueError, KeyError, TypeError:
        return None


def judge_vlans(status: int, body: str, tags: tuple[int, ...]) -> tuple[bool, str]:
    """Whether the gateway has the VLAN interfaces `tags` calls for, and one sentence saying what was found."""
    if status != 200:
        return False, f"the gateway's interface list answered HTTP {status}" if status else "the gateway's interface list gave no answer"
    names = interface_names(body)
    if names is None:
        return False, "the gateway's interface list is not in the shape this check reads"
    found = sorted((name for name in names if OPTIONAL_INTERFACE_RE.fullmatch(name)), key=lambda name: int(name[3:]))
    wanted = [f"opt{number}" for number in range(1, len(tags) + 1)]
    seeded = f"the spec seeds {len(tags)} VLANs ({', '.join(str(tag) for tag in tags)})"
    has = f"the gateway has {len(found)} VLAN interfaces ({', '.join(found) or 'none'})"
    return found == wanted, f"{has}; {seeded}"
