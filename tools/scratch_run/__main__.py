"""The single command for a scratch-gateway run.

    python -m scratch_run --init-env                 write the settings file to fill in, once
    python -m scratch_run --list                     the specs there are
    python -m scratch_run SPEC [--preflight]         check what the run needs, then stop
    python -m scratch_run SPEC [--keep]              run it
    python -m scratch_run SPEC --check-spec          read the spec and check it against the flow list, nothing else

Run from `tools/`. SPEC is a name such as `rehearsal` (a file in `tofu/scratch/opnsense/runs/`) or a path. The node, the
token, the image, OUT_DIR and the rest come from the settings file (`~/.config/homelab/scratch-run.env`, or `--env-file`),
a real environment variable or a flag, in that order of increasing weight; see `scratch_run.settings`. OUT_DIR holds the
gateway's state and credentials, must be outside the repository, and gets the results in OUT_DIR/<name>-<stamp>/ and one
archive. Exit status: 0 every step had its expected outcome, 1 one did not, 2 the run could not start.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from scratch_run.engine import EXIT_NOT_RUN, EXIT_OK, Backend, run
from scratch_run.node import REPO, NodeBackend
from scratch_run.settings import DEFAULT_ENV_FILE, IMAGE_CHECKSUM, IMAGE_URL, OUT_DIR, SettingsError, init_env_file, merge, read_env_file
from scratch_run.spec import SpecError, load_spec

RUNS = REPO / "tofu" / "scratch" / "opnsense" / "runs"
BackendFactory = Callable[[Path, str, str, Mapping[str, str]], Backend]


def find_spec(name: str) -> Path:
    for candidate in (Path(name), RUNS / f"{name}.yaml"):
        if candidate.is_file():
            return candidate
    known = ", ".join(sorted(path.stem for path in RUNS.glob("*.yaml")))
    raise SpecError(f"no spec `{name}`; the specs are: {known}")


def list_specs() -> None:
    for path in sorted(RUNS.glob("*.yaml")):
        try:
            print(f"{path.stem}: {load_spec(path).description}")
        except SpecError as error:
            print(f"{path.stem}: NOT VALID ({error.args[0].splitlines()[0]})")


def main(argv: list[str] | None = None, environ: Mapping[str, str] | None = None, backend_factory: BackendFactory = NodeBackend) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("spec", nargs="?")
    parser.add_argument("out_dir", type=Path, nargs="?", help=f"default: {OUT_DIR} in the settings")
    parser.add_argument("--image-url", help=f"default: {IMAGE_URL} in the settings")
    parser.add_argument("--image-checksum", help=f"default: {IMAGE_CHECKSUM} in the settings")
    parser.add_argument("--env-file", type=Path, help=f"default: {DEFAULT_ENV_FILE}, when it exists")
    parser.add_argument("--keep", action="store_true", help="leave the gateway up when the steps are done")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check-spec", action="store_true", help="only read the spec and check it against the flow list")
    mode.add_argument("--preflight", action="store_true", help="check the spec and what the run needs, then stop")
    mode.add_argument("--list", action="store_true", help="list the specs")
    mode.add_argument("--init-env", action="store_true", help="write the settings file, to fill in")
    args = parser.parse_args(argv)
    try:
        if args.init_env:
            path = init_env_file(args.env_file or DEFAULT_ENV_FILE)
            print(f"wrote {path} (mode 600); fill it in, then: python -m scratch_run --list")
            return EXIT_OK
        if args.list:
            list_specs()
            return EXIT_OK
        if args.spec is None:
            parser.error("a SPEC is needed (see --list)")
        spec_path = find_spec(args.spec)
        spec = load_spec(spec_path)
        if args.check_spec:
            print(f"{spec.name}: {len(spec.steps)} steps, valid")
            return EXIT_OK
        env_file = args.env_file or DEFAULT_ENV_FILE
        from_file = read_env_file(env_file, REPO) if args.env_file or env_file.expanduser().is_file() else {}
    except (SpecError, SettingsError) as error:
        print(error, file=sys.stderr)
        return EXIT_NOT_RUN
    env = merge(os.environ if environ is None else environ, from_file)
    chosen = args.out_dir or (Path(env[OUT_DIR]) if env.get(OUT_DIR) else None)
    if chosen is None:
        print(f"no OUT_DIR: give one after the spec or set {OUT_DIR} in the settings", file=sys.stderr)
        return EXIT_NOT_RUN
    out_dir = chosen.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    backend = backend_factory(out_dir, args.image_url or env.get(IMAGE_URL, ""), args.image_checksum or env.get(IMAGE_CHECKSUM, ""), env)
    if args.preflight:
        problems = backend.preflight(spec)
        print("\n".join(f"- {problem}" for problem in problems) if problems else f"{spec.name}: ready to run")
        return EXIT_NOT_RUN if problems else EXIT_OK
    return run(spec, backend, out_dir, time.strftime("%Y%m%d-%H%M%S"), time.monotonic, keep=args.keep)


if __name__ == "__main__":
    sys.exit(main())
