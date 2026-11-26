"""Usage (from tools/):
python -m doc_site [--commit SHA] --out DIR      build into DIR, which is empty or absent
python -m doc_site [--commit SHA] --serve [--port N]   build into a temporary directory and serve it until stopped
"""

from __future__ import annotations

import argparse
import functools
import http.server
import re
import signal
import subprocess
import tempfile
from pathlib import Path

from doc_scripts.doc_frontmatter import ROOT

from doc_site import site

DEFAULT_PORT = 8000
# Ctrl-C, a closed terminal and a plain `kill`. The last two end a process, at their defaults, before it removes anything.
STOP_SIGNALS = (signal.SIGINT, signal.SIGHUP, signal.SIGTERM)


def stamp_of(commit: str) -> site.Stamp:
    """The footer's stamp for `commit`, whose date the repository supplies. The build itself reads no git state: it is given this."""
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise SystemExit(f"--commit takes a full 40-character commit id, not {commit!r}")
    shown = subprocess.run(["git", "-C", str(ROOT), "show", "-s", "--format=%cI", commit], capture_output=True, text=True, check=False)
    if shown.returncode != 0:
        raise SystemExit(f"{commit} is not a commit of {ROOT}: {shown.stderr.strip()}")
    return site.Stamp(commit, shown.stdout.strip())


def _stop(signum, frame) -> None:
    # One stop can arrive twice (`uv run` forwards a signal the process group already got), and a second one would cut the removal short.
    for other in STOP_SIGNALS:
        signal.signal(other, signal.SIG_IGN)
    raise KeyboardInterrupt


def preview(port: int, stamp: site.Stamp | None = None) -> None:
    """Builds the site into a temporary directory, serves it on localhost until Ctrl-C or a stop signal, then removes it."""
    previous = {signum: signal.signal(signum, _stop) for signum in STOP_SIGNALS}
    try:
        with tempfile.TemporaryDirectory(prefix="doc-site-") as directory:
            handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
            # Bound before the build, so a port in use is reported at once.
            try:
                server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
            except OSError as error:
                raise SystemExit(f"cannot serve on port {port}: {error.strerror}; choose another with --port") from error
            with server:
                written = site.write(Path(directory), stamp=stamp)
                print(f"Wrote {len(written)} files. Serving http://127.0.0.1:{server.server_address[1]}/ until Ctrl-C.", flush=True)
                server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped; the built site is removed.")
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the documentation views as a static site.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--out", type=Path, help="directory to write the site into; must be empty or absent")
    target.add_argument("--serve", action="store_true", help="build into a temporary directory, serve it on localhost and remove it when stopped")
    parser.add_argument("--port", type=int, help=f"with --serve, the port to listen on (default {DEFAULT_PORT})")
    parser.add_argument(
        "--commit",
        help="full id of the commit being built; the footer names it and its date. Without it the footer says 'Local build'",
    )
    args = parser.parse_args(argv)
    if args.port is not None and not args.serve:
        parser.error("--port goes with --serve")
    stamp = stamp_of(args.commit) if args.commit else None
    if args.serve:
        preview(DEFAULT_PORT if args.port is None else args.port, stamp)
        return 0
    written = site.write(args.out, stamp=stamp)
    print(f"Wrote {len(written)} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
