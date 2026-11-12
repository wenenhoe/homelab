"""The two-zone flow list the scratch plan and the namespace canaries are tested with."""

from __future__ import annotations

FLOWS = {
    "zones": {
        "services": {"subnet": "192.168.20.0/24", "canary": "192.168.20.8"},
        "desktops": {"subnet": "192.168.40.0/24", "canary": "192.168.40.8"},
    },
    "flows": [
        {"id": "services-canary-ssh", "from": "services", "to": {"address": "192.168.20.8", "port": 22}, "kind": "connect", "expect": "allow"},
        {"id": "desktops-canary-ssh", "from": "desktops", "to": {"address": "192.168.40.8", "port": 22}, "kind": "connect", "expect": "allow"},
        {"id": "desktops-vault-allowed", "from": "desktops", "to": {"address": "192.168.20.5", "port": 8200}, "kind": "connect", "expect": "allow"},
        {
            "id": "desktops-to-services-canary-denied",
            "from": "desktops",
            "to": {"address": "192.168.20.8", "port": 22},
            "kind": "connect",
            "expect": "deny",
            "control": "services-canary-ssh",
        },
        {
            "id": "services-to-desktops-canary-denied",
            "from": "services",
            "to": {"address": "192.168.40.8", "port": 22},
            "kind": "connect",
            "expect": "deny",
            "control": "desktops-canary-ssh",
        },
    ],
}
VLANS = {"services": 20, "desktops": 40}
