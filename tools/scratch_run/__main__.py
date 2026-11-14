"""The single command for a scratch-gateway run.

    python -m scratch_run SPEC OUT_DIR --image-url URL --image-checksum SHA256 [--keep] [--preflight | --check-spec]

Run from `tools/`. SPEC is a file like `tofu/scratch/opnsense/runs/rehearsal.yaml`. OUT_DIR holds the gateway's state
and credentials and must be outside the repository; the results go to OUT_DIR/<name>-<stamp>/ and one archive.
The environment is `scratch_gateway.sh`'s: NODE, PROXMOX_ENDPOINT, PROXMOX_API_TOKEN, VM_ID, LAN_BRIDGE and the rest.
Exit status: 0 every step had its expected outcome, 1 one did not, 2 the run could not start.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from scratch_run.engine import EXIT_NOT_RUN, EXIT_OK, Backend, run
from scratch_run.node import NodeBackend
from scratch_run.spec import SpecError, load_spec

BackendFactory = Callable[[Path, str, str, Mapping[str, str]], Backend]


def main(argv: list[str] | None = None, environ: Mapping[str, str] | None = None, backend_factory: BackendFactory = NodeBackend) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("spec", type=Path)
    parser.add_argument("out_dir", type=Path, nargs="?")
    parser.add_argument("--image-url", default="")
    parser.add_argument("--image-checksum", default="")
    parser.add_argument("--keep", action="store_true", help="leave the gateway up when the steps are done")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check-spec", action="store_true", help="only read the spec and check it against the flow list")
    mode.add_argument("--preflight", action="store_true", help="check the spec and what the run needs, then stop")
    args = parser.parse_args(argv)
    try:
        spec = load_spec(args.spec)
    except SpecError as error:
        print(f"{args.spec} is not a valid spec:\n{error}", file=sys.stderr)
        return EXIT_NOT_RUN
    if args.check_spec:
        print(f"{spec.name}: {len(spec.steps)} steps, valid")
        return EXIT_OK
    if args.out_dir is None:
        parser.error("OUT_DIR is required unless --check-spec is given")
    out_dir = args.out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    backend = backend_factory(out_dir, args.image_url, args.image_checksum, os.environ if environ is None else environ)
    if args.preflight:
        problems = backend.preflight(spec)
        print("\n".join(f"- {problem}" for problem in problems) if problems else f"{spec.name}: ready to run")
        return EXIT_NOT_RUN if problems else EXIT_OK
    return run(spec, backend, out_dir, time.strftime("%Y%m%d-%H%M%S"), time.monotonic, keep=args.keep)


if __name__ == "__main__":
    sys.exit(main())
