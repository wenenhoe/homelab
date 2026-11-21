"""Usage (from tools/): python -m doc_site [--commit SHA] --out DIR   (DIR empty or absent)"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

from doc_scripts.doc_frontmatter import ROOT

from doc_site import site


def stamp_of(commit: str) -> site.Stamp:
    """The footer's stamp for `commit`, whose date the repository supplies. The build itself reads no git state: it is given this."""
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise SystemExit(f"--commit takes a full 40-character commit id, not {commit!r}")
    shown = subprocess.run(["git", "-C", str(ROOT), "show", "-s", "--format=%cI", commit], capture_output=True, text=True, check=False)
    if shown.returncode != 0:
        raise SystemExit(f"{commit} is not a commit of {ROOT}: {shown.stderr.strip()}")
    return site.Stamp(commit, shown.stdout.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the documentation views as a static site.")
    parser.add_argument("--out", type=Path, required=True, help="directory to write the site into; must be empty or absent")
    parser.add_argument(
        "--commit",
        help="full id of the commit being built; the footer names it and its date. Without it the footer says 'Local build'",
    )
    args = parser.parse_args(argv)
    written = site.write(args.out, stamp=stamp_of(args.commit) if args.commit else None)
    print(f"Wrote {len(written)} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
