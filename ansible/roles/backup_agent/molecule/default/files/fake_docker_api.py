"""A stand-in Docker API socket: answers 200 to every request and logs what reached it.

usage: fake_docker_api.py SOCKET_PATH LOG_PATH

Each request is appended to LOG_PATH as one JSON line, [method, raw request target], before
the response is sent, so a reader that has seen the response sees the line.
"""

import json
import os
import socketserver
import sys
from http.server import BaseHTTPRequestHandler

SOCKET_PATH, LOG_PATH = sys.argv[1:3]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def handle_any(self):
        with open(LOG_PATH, "a") as log:
            log.write(json.dumps([self.command, self.path]) + "\n")
        body = b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    do_GET = do_HEAD = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = handle_any

    def log_message(self, *args):
        pass

    def address_string(self):
        return "unix"


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


# Created world-connectable, so the proxy can reach it whichever user its image runs as.
os.umask(0)
open(LOG_PATH, "a").close()
with Server(SOCKET_PATH, Handler) as server:
    server.serve_forever()
