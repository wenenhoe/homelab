"""A real requests.Session whose network calls are replaced for a test.

The session is the library's own, so what the code under test sets on it
(headers, auth) is kept and read back as it would be. Every method that
can reach the network is an autospec'd stand-in bound to the real
signature: a call the real one would reject fails, and none can leave the
process. A test sets `.return_value` or `.side_effect` on the method it
expects the code to call.
"""

from __future__ import annotations

from unittest.mock import create_autospec

import requests

_NETWORK_METHODS = ("get", "options", "head", "post", "put", "patch", "delete", "request", "send")


def stubbed_session() -> requests.Session:
    session = requests.Session()
    for name in _NETWORK_METHODS:
        setattr(session, name, create_autospec(getattr(session, name)))
    return session
