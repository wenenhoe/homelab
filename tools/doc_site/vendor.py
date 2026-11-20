"""The vendored stylesheet and the pin that says which published file it is.

`vendor/simple.pin` names an npm package, its version, the file taken from it, that file's
sha256 and the GitHub repository the package is built from. The file is committed beside it, so
the site makes no request to a third party and a build needs no network. A test holds the file
to the pin; `--upstream` holds both to the registry's tarball and to the same file at the
repository's `v<version>` tag, so a tarball that differs from the source fails; and
`--update VERSION` replaces the file and the pin together after the same two-way comparison,
which is how a version Renovate proposes is taken in.

Usage (from tools/): python -m doc_site.vendor [--upstream | --update VERSION]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import re
import sys
import tarfile
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

VENDOR = Path(__file__).resolve().parent / "vendor"
PIN = VENDOR / "simple.pin"
REGISTRY = "https://registry.npmjs.org"
RAW = "https://raw.githubusercontent.com"
HOSTS = (f"{REGISTRY}/", f"{RAW}/")
FETCH_TIMEOUT = 60
MAX_BYTES = 5_000_000

Fetch = Callable[[str], bytes]


class VendorError(Exception):
    """The pin, the file or the published package is not what it should be."""


@dataclass(frozen=True)
class Pin:
    package: str
    version: str
    file: str
    sha256: str
    repository: str


def read_pin(path: Path = PIN) -> Pin:
    fields: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        key, separator, value = line.partition(" = ")
        if not separator or key in fields:
            raise VendorError(f"{path.name}: expected one `key = value` line per key, got {line!r}")
        fields[key] = value.strip()
    if set(fields) != {"package", "version", "file", "sha256", "repository"}:
        raise VendorError(f"{path.name}: keys must be package, version, file, sha256 and repository, got {sorted(fields)}")
    pin = Pin(**fields)
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", pin.package) or not re.fullmatch(r"\d+\.\d+\.\d+", pin.version):
        raise VendorError(f"{path.name}: package or version is not in the expected form")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", pin.file) or not re.fullmatch(r"[0-9a-f]{64}", pin.sha256):
        raise VendorError(f"{path.name}: file or sha256 is not in the expected form")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", pin.repository):
        raise VendorError(f"{path.name}: repository is not in the form owner/name")
    return pin


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def local_errors(vendor: Path = VENDOR, pin_path: Path = PIN) -> list[str]:
    """Whether the committed file is the one the pin names, with nothing to fetch."""
    pin = read_pin(pin_path)
    target = vendor / pin.file
    if not target.is_file():
        return [f"{target.name} is not in {vendor.name}/"]
    actual = digest(target.read_bytes())
    if actual != pin.sha256:
        return [f"{target.name} has sha256 {actual}, but the pin says {pin.sha256}; run `python -m doc_site.vendor --update {pin.version}`"]
    return []


def tarball_url(package: str, version: str) -> str:
    return f"{REGISTRY}/{package}/-/{package}-{version}.tgz"


def source_url(repository: str, version: str, file: str) -> str:
    return f"{RAW}/{repository}/v{version}/{file}"


def http_fetch(url: str) -> bytes:
    if not url.startswith(HOSTS):
        raise VendorError(f"refusing to fetch {url}")
    with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT) as response:  # noqa: S310 - the host is checked above
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise VendorError(f"{url} is larger than {MAX_BYTES} bytes")
    return data


def published_file(package: str, version: str, file: str, fetch: Fetch = http_fetch) -> bytes:
    """`file` from the published tarball of `package@version`, read in memory and never extracted."""
    with tarfile.open(fileobj=io.BytesIO(fetch(tarball_url(package, version))), mode="r:gz") as archive:
        try:
            member = archive.getmember(f"package/{file}")
        except KeyError:
            raise VendorError(f"{package}@{version} has no {file}") from None
        if not member.isfile() or member.size > MAX_BYTES:
            raise VendorError(f"{package}@{version}: package/{file} is not a regular file of a sane size")
        stream = archive.extractfile(member)
        if stream is None:
            raise VendorError(f"{package}@{version}: package/{file} cannot be read")
        return stream.read()


def source_digest(pin: Pin, version: str, fetch: Fetch) -> str:
    return digest(fetch(source_url(pin.repository, version, pin.file)))


def upstream_errors(fetch: Fetch = http_fetch, vendor: Path = VENDOR, pin_path: Path = PIN) -> list[str]:
    """Whether the committed file and the pin match the registry's tarball and the repository's tagged file."""
    pin = read_pin(pin_path)
    published = digest(published_file(pin.package, pin.version, pin.file, fetch))
    errors = []
    tagged = source_digest(pin, pin.version, fetch)
    if tagged != published:
        errors.append(f"{pin.package}@{pin.version} publishes {pin.file} with sha256 {published}, but {pin.repository} at v{pin.version} has {tagged}")
    if published != pin.sha256:
        errors.append(f"{pin.package}@{pin.version} publishes {pin.file} with sha256 {published}, but the pin says {pin.sha256}")
    target = vendor / pin.file
    if not target.is_file() or digest(target.read_bytes()) != published:
        errors.append(f"{target.name} is not the file {pin.package}@{pin.version} publishes; run `python -m doc_site.vendor --update {pin.version}`")
    return errors


def update(version: str, fetch: Fetch = http_fetch, vendor: Path = VENDOR, pin_path: Path = PIN) -> Pin:
    """Replaces the vendored file and the pin with `version` of the pinned package."""
    old = read_pin(pin_path)
    body = published_file(old.package, version, old.file, fetch)
    new = Pin(old.package, version, old.file, digest(body), old.repository)
    tagged = source_digest(new, version, fetch)
    if tagged != new.sha256:
        raise VendorError(
            f"{old.package}@{version} publishes {old.file} with sha256 {new.sha256}, but {old.repository} at v{version} has {tagged}; nothing was written"
        )
    text = f"package = {new.package}\nversion = {new.version}\nfile = {new.file}\nsha256 = {new.sha256}\nrepository = {new.repository}\n"
    (vendor / new.file).write_bytes(body)
    pin_path.write_text(text, encoding="utf-8")
    read_pin(pin_path)
    return new


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--upstream", action="store_true", help="also compare the file and the pin with the registry's tarball and the repository's tag")
    group.add_argument("--update", metavar="VERSION", help="take VERSION from the registry: replace the file and the pin")
    args = parser.parse_args(argv)
    try:
        if args.update:
            pin = update(args.update)
            print(f"Vendored {pin.package}@{pin.version} ({pin.file}, sha256 {pin.sha256}).")
            return 0
        errors = local_errors() + (upstream_errors() if args.upstream else [])
    except (VendorError, OSError, tarfile.TarError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
