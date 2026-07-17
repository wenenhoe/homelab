import http.client
import os

docker_host_env = os.environ.get("DOCKER_HOST", "tcp://dockerproxy:2375")
host_port = docker_host_env.replace("tcp://", "").split(":")
proxy_host = host_port[0]
proxy_port = int(host_port[1]) if len(host_port) > 1 else 2375

try:
    # Connect directly via TCP instead of a UNIX socket
    conn = http.client.HTTPConnection(proxy_host, port=proxy_port, timeout=10)
    conn.request("POST", "/containers/lldap/restart")
    resp = conn.getresponse()
    body = resp.read().decode(errors="replace")
    conn.close()

    if resp.status == 204:
        print("[deploy-hook] restarted lldap container via proxy")
    else:
        print(f"[deploy-hook] WARNING: restart returned HTTP {resp.status}: {body}")
except Exception as exc:
    print(f"[deploy-hook] WARNING: failed to restart lldap via proxy: {exc}")
