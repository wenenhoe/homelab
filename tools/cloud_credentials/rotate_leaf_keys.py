#!/usr/bin/env python3
"""Rotate both leaf keys of every provider in one run: B2, then OCI, then R2.

Each provider goes through the same create, verify, then revoke path as
`create_leaf_keys --provider <x> --rotate both`. This runs the three in
turn, so one command rotates all six leaf credentials. A provider that
fails, by reporting a failed verification, by exiting or by raising, does
not stop the providers after it, and the exit status is 1 if any failed.
See docs/topics/secrets/cloud-credentials/rotation.md.

Usage (run from tools/):
    python3 -m cloud_credentials.rotate_leaf_keys
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from cloud_credentials.create_leaf_keys import _PROVIDER_ERRORS, _format_provider_error
from cloud_credentials.leaf_keys.b2 import rotate_b2
from cloud_credentials.leaf_keys.oci import rotate_oci
from cloud_credentials.leaf_keys.r2 import rotate_r2


def _rotate(provider: str, rotate: Callable[[list[str]], bool]) -> bool:
    try:
        return rotate(["write", "read"])
    except _PROVIDER_ERRORS as exc:
        print(f"{provider}: request failed: {_format_provider_error(exc)}", file=sys.stderr)
    # The cache and leaf modules report a missing secret or bucket with
    # sys.exit; letting it through would skip every provider after this one.
    except SystemExit:
        print(f"{provider}: stopped before finishing", file=sys.stderr)
    except Exception as exc:
        print(f"{provider}: rotation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    return False


def main() -> int:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()

    providers = {"b2": rotate_b2, "oci": rotate_oci, "r2": rotate_r2}
    failed = []
    for name, rotate in providers.items():
        if not _rotate(name, rotate):
            failed.append(name)

    if failed:
        print(f"rotation failed for: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
