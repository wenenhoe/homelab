import http.client
import socket


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path, timeout=10):
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.socket_path)
        self.sock = sock


try:
    conn = UnixHTTPConnection("/var/run/docker.sock")
    conn.request("POST", "/containers/lldap/restart")
    resp = conn.getresponse()
    body = resp.read().decode(errors="replace")
    conn.close()
    if resp.status == 204:
        print("[deploy-hook] restarted lldap container")
    else:
        print(f"[deploy-hook] WARNING: restart returned HTTP {resp.status}: {body}")
except Exception as exc:
    print(f"[deploy-hook] WARNING: failed to restart lldap via docker socket: {exc}")
