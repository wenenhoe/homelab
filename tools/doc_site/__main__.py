"""Usage (from tools/): python -m doc_site --out DIR   (DIR empty or absent)"""

from __future__ import annotations

import argparse
from pathlib import Path

from doc_site import site


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the documentation views as a static site.")
    parser.add_argument("--out", type=Path, required=True, help="directory to write the site into; must be empty or absent")
    written = site.write(parser.parse_args(argv).out)
    print(f"Wrote {len(written)} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
