#!/usr/bin/python3 -I
"""runc wrapper: makes each new container trust the certificate authorities the session's environment added.

`cloud_session.prepare` copies this file to the session's machine and names it as dockerd's runtime, so it runs by itself
on that machine's python3 and imports only the standard library.
"""

import glob
import json
import os
import re
import sys

RUNC = "/usr/bin/runc"
BUNDLE = "/root/.ccr/ca-bundle.crt"
STANDARD = "/usr/share/ca-certificates/mozilla/*.crt"
PEM = re.compile(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", re.DOTALL)


def certificates(path):
    with open(path) as handle:
        return PEM.findall(handle.read())


def key(certificate):
    return "".join(certificate.split())


def added(bundle=BUNDLE, standard=STANDARD):
    """The certificates in the environment's bundle that Mozilla's set lacks."""
    known = {key(c) for path in glob.glob(standard) for c in certificates(path)}
    if not known:
        sys.exit("runc-ca: no Mozilla certificates to compare against")
    return list({key(c): c for c in certificates(bundle) if key(c) not in known}.values())


def trust(root, extra):
    """Add `extra` to the trust store of the container filesystem at `root`, and write nothing outside it."""
    root = os.path.realpath(root)

    def inside(path):
        # An image's symlink must not send a write outside its own root.
        return os.path.realpath(path).startswith(root + os.sep)

    store = os.path.join(root, "etc/ssl/certs/ca-certificates.crt")
    if not inside(store) or not os.path.isfile(store):
        return
    present = {key(c) for c in certificates(store)}
    missing = [c for c in extra if key(c) not in present]
    if missing:
        with open(store, "a") as handle:
            handle.write("\n" + "\n".join(missing) + "\n")
    local = os.path.join(root, "usr/local/share/ca-certificates")
    if not inside(local):
        return
    os.makedirs(local, exist_ok=True)
    # One certificate to a file, so update-ca-certificates in the container keeps them.
    for number, certificate in enumerate(extra):
        target = os.path.join(local, f"session-egress-{number}.crt")
        if not os.path.islink(target):
            with open(target, "w") as handle:
                handle.write(certificate + "\n")


def container_root(args):
    """The filesystem of the container `args` create, or None when they create none."""
    if "create" not in args or "--bundle" not in args:
        return None
    bundle = args[args.index("--bundle") + 1]
    with open(os.path.join(bundle, "config.json")) as handle:
        return os.path.join(bundle, json.load(handle)["root"]["path"])


def main(args):
    root = container_root(args)
    if root is not None:
        trust(root, added())
    os.execv(RUNC, ["runc", *args])  # noqa: S606 -- hands over to runc with the arguments dockerd gave


if __name__ == "__main__":
    main(sys.argv[1:])
