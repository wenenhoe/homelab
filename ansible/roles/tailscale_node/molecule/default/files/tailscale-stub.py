#!/usr/bin/env python3
"""A stand-in for the tailscale client in the role's Molecule scenarios.

Answers the four calls the role makes (`status --json`, `debug prefs`, `up`,
`set`) from a state file, so the join and the preference comparison run
without a control plane. `debug prefs` prints the keys a real node reports,
with the values recorded from real nodes. Every call is appended to a log
that holds the subcommand and the names of the flags, never their values.
"""

import json
import os
import sys

STATE_DIR = os.environ.get("TAILSCALE_STUB_DIR", "/var/lib/tailscale-stub")
STATE = os.path.join(STATE_DIR, "state.json")
CALLS = os.path.join(STATE_DIR, "calls.log")


def load():
    with open(STATE) as handle:
        return json.load(handle)


def save(state):
    with open(STATE, "w") as handle:
        json.dump(state, handle)


def log(line):
    with open(CALLS, "a") as handle:
        handle.write(line + "\n")


def flags(args):
    parsed = {}
    for arg in args:
        name, _, value = arg.partition("=")
        parsed[name[2:]] = value
    return parsed


def to_bool(name, value):
    if value not in ("true", "false"):
        sys.exit(f"stub: --{name} takes true or false")
    return value == "true"


def main(argv):
    state = load()
    command = " ".join(argv[:2]) if argv[:1] == ["debug"] else argv[0]
    parsed = flags([a for a in argv[1:] if a.startswith("--")])
    log(" ".join([command, *sorted(parsed)]))

    if argv[:2] == ["status", "--json"]:
        backend = "Running" if state["logged_in"] else "NeedsLogin"
        print(json.dumps({"BackendState": backend}))
    elif argv[:2] == ["debug", "prefs"]:
        print(json.dumps(state["prefs"], indent="\t"))
    elif argv[0] == "up":
        if state["logged_in"]:
            sys.exit("stub: up on a node that is already logged in")
        key = parsed.get("auth-key") or parsed.get("authkey")
        if not key:
            sys.exit("stub: up without an auth key")
        if not parsed.get("advertise-tags"):
            sys.exit("stub: up without a tag")
        state["logged_in"] = True
        state["tags"] = parsed["advertise-tags"]
        save(state)
    elif argv[0] == "set":
        prefs = state["prefs"]
        for name, value in parsed.items():
            if name == "advertise-routes":
                prefs["AdvertiseRoutes"] = value.split(",") if value else None
            elif name == "accept-dns":
                prefs["CorpDNS"] = to_bool(name, value)
            elif name == "auto-update":
                prefs["AutoUpdate"]["Apply"] = to_bool(name, value)
            else:
                sys.exit(f"stub: unsupported preference --{name}")
        save(state)
    else:
        sys.exit(f"stub: unsupported command {argv}")


if __name__ == "__main__":
    main(sys.argv[1:])
