"""Flow lists the network_checks tests load."""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

GOOD = {
    "zones": {
        "alpha": {"subnet": "10.1.0.0/24", "canary": "10.1.0.250"},
        "beta": {"subnet": "10.2.0.0/24", "canary": "10.2.0.250"},
    },
    "flows": [
        {
            "id": "alpha-dns",
            "from": "alpha",
            "to": {"address": "10.2.0.1", "port": 53, "protocol": "udp"},
            "kind": "dns",
            "query": "host.lab",
            "expect": "allow",
            "tags": ["smoke"],
        },
        {"id": "beta-web", "from": "beta", "to": {"address": "10.1.0.1", "port": 443}, "kind": "connect", "expect": "allow"},
        {"id": "alpha-ssh-blocked", "from": "alpha", "to": {"address": "10.2.0.1", "port": 22}, "kind": "connect", "expect": "deny", "control": "alpha-ssh"},
        {"id": "alpha-ssh", "from": "beta", "to": {"address": "10.2.0.1", "port": 22}, "kind": "connect", "expect": "allow"},
    ],
}


@pytest.fixture
def good() -> dict:
    """A flow list that passes the loader and every rule; a test changes the copy it gets."""
    return copy.deepcopy(GOOD)


@pytest.fixture
def write_flows(tmp_path: Path) -> Callable[[object], Path]:
    def write(data: object) -> Path:
        path = tmp_path / "flows.yaml"
        path.write_text(data if isinstance(data, str) else yaml.safe_dump(data))
        return path

    return write
