"""Send each call to the proxy and compare the answer, and what reached the fake socket, with what was expected.

usage: check_docker_api_rules.py HOST PORT SOCKET_LOG CASES_JSON

CASES_JSON is {"allowed": [[method, target], ...], "refused": [[method, target], ...]}. An allowed
call must get a 200 and reach the socket once, as the same method and target. A refused call must
get a 403 and must not reach the socket. Exits 1 on any mismatch, or when there are no calls.
"""

import http.client
import json
import sys

host, port, socket_log, cases_json = sys.argv[1:5]
port = int(port)
with open(cases_json) as cases_file:
    cases = json.load(cases_file)


def send(method, target):
    """Make one call on its own connection; return the status and the socket's log lines."""
    with open(socket_log, "w"):
        pass
    connection = http.client.HTTPConnection(host, port, timeout=10)
    connection.putrequest(method, target, skip_accept_encoding=True)
    if method in ("POST", "PUT", "PATCH"):
        connection.putheader("Content-Length", "0")
    connection.endheaders()
    response = connection.getresponse()
    response.read()
    connection.close()
    with open(socket_log) as log:
        return response.status, [json.loads(line) for line in log]


mismatches = 0
total = 0
for verdict, status_wanted in (("allowed", 200), ("refused", 403)):
    for method, target in cases[verdict]:
        total += 1
        status, reached = send(method, target)
        reached_wanted = [[method, target]] if verdict == "allowed" else []
        if status == status_wanted and reached == reached_wanted:
            print(f"ok   {verdict:7} {method:6} {target}")
        else:
            mismatches += 1
            print(f"BAD  {verdict:7} {method:6} {target}  -> {status}, socket saw {reached}, wanted {status_wanted} and {reached_wanted}")

print(f"{total - mismatches} of {total} calls as expected")
sys.exit(1 if mismatches or not total else 0)
