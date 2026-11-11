"""Runs on a canary: tries each flow it is given once and prints one JSON result per line (ADR 0094).

The runner sends this file on the standard input of the canary's `python3`, so it uses the standard library only
and nothing it needs is installed on the canary. The flows come as one JSON argument, a list of objects with
`id`, `kind`, `address`, `port`, `protocol`, `query` and `timeout`. Each result is `{"id", "status", "detail"}`:
`ok` when the attempt succeeded, `failed` when it did not (refused, silent, unreachable), and `error` when the
probe itself could not be run, which the runner counts as a failure even for a deny.

Every probe opens a new connection: a rule that cuts new connections leaves open ones working.
"""

import json
import random
import socket
import struct
import subprocess
import sys

OK, FAILED, ERROR = "ok", "failed", "error"
PING = "ping"
DNS_QUERY_TYPE_A = 1
DNS_CLASS_IN = 1
DNS_RESPONSE_FLAG = 0x8000
NTP_PACKET = b"\x1b" + 47 * b"\x00"
NTP_SERVER_MODE = 4


class ProbeError(Exception):
    """The probe cannot be run as asked."""


def _connect(spec):
    with socket.create_connection((spec["address"], spec["port"]), timeout=spec["timeout"]):
        return (OK, "connected")


def _dns_message(name):
    """A recursive A query for `name`, and the id it carries."""
    query_id = random.randrange(1 << 16)  # noqa: S311 - an id to match the answer to the question, not a secret
    labels = b"".join(bytes([len(label)]) + label.encode("ascii") for label in name.rstrip(".").split("."))
    return query_id, struct.pack(">HHHHHH", query_id, 0x0100, 1, 0, 0, 0) + labels + b"\x00" + struct.pack(">HH", DNS_QUERY_TYPE_A, DNS_CLASS_IN)


def _answered(query_id, reply):
    """The response code of `reply` when it answers the query with `query_id`, else none."""
    if len(reply) < 12:
        return None
    reply_id, flags = struct.unpack(">HH", reply[:4])
    if reply_id != query_id or not flags & DNS_RESPONSE_FLAG:
        return None
    return flags & 0xF


def _read_exactly(sock, count):
    data = b""
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise ConnectionError("closed before the reply was complete")
        data += chunk
    return data


def _dns(spec):
    query_id, message = _dns_message(spec["query"])
    if spec["protocol"] == "tcp":
        with socket.create_connection((spec["address"], spec["port"]), timeout=spec["timeout"]) as sock:
            sock.sendall(struct.pack(">H", len(message)) + message)
            reply = _read_exactly(sock, struct.unpack(">H", _read_exactly(sock, 2))[0])
    else:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(spec["timeout"])
            sock.sendto(message, (spec["address"], spec["port"]))
            reply = sock.recv(4096)
    code = _answered(query_id, reply)
    if code is None:
        return (FAILED, "the reply did not answer the query")
    return (OK, f"answered with response code {code}")


def _ntp(spec):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(spec["timeout"])
        sock.sendto(NTP_PACKET, (spec["address"], spec["port"]))
        reply = sock.recv(512)
    if len(reply) < 48 or reply[0] & 7 != NTP_SERVER_MODE:
        return (FAILED, "the reply was not an NTP server response")
    return (OK, "answered")


def _ping(spec):
    try:
        done = subprocess.run(
            [PING, "-c", "1", "-W", str(max(1, int(spec["timeout"]))), spec["address"]],
            capture_output=True,
            text=True,
            check=False,
            timeout=spec["timeout"] + 5,
        )
    except FileNotFoundError as exc:
        raise ProbeError("ping is not installed on the canary") from exc
    except subprocess.TimeoutExpired:
        return (FAILED, "no reply")
    return (OK, "replied") if done.returncode == 0 else (FAILED, "no reply")


PROBES = {"connect": _connect, "dns": _dns, "ntp": _ntp, "ping": _ping}


def probe(spec):
    """Try one flow and return its result. A refusal, a silence and an unreachable network are `failed`."""
    flow_id = spec.get("id")
    if spec.get("kind") not in PROBES:
        return {"id": flow_id, "status": ERROR, "detail": f"unknown kind {spec.get('kind')!r}"}
    try:
        status, detail = PROBES[spec["kind"]](spec)
    except KeyError as exc:
        return {"id": flow_id, "status": ERROR, "detail": f"the flow is missing {exc}"}
    except ProbeError as exc:
        return {"id": flow_id, "status": ERROR, "detail": str(exc)}
    except OSError as exc:  # a refusal, a timeout, an unreachable network or a closed connection
        return {"id": flow_id, "status": FAILED, "detail": f"{type(exc).__name__}: {exc}"}
    return {"id": flow_id, "status": status, "detail": detail}


def _flows(argv):
    """The flows in the first argument, or none when there is no argument or it is not JSON."""
    if len(argv) < 2:
        return None
    try:
        return json.loads(argv[1])
    except ValueError:
        return None


def main(argv):
    specs = _flows(argv)
    if specs is None:
        print(json.dumps({"id": None, "status": ERROR, "detail": "no flows were given"}), flush=True)
        return 2
    for spec in specs:
        print(json.dumps(probe(spec)), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
