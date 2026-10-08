#!/usr/bin/env python3
"""Is each pinned release checksum the one its publisher released?

Every pin in the registry (ci.checksums.registry) is compared with what its
publisher offers, to the degree its tier allows: a signed manifest verified
against the key committed for it, a build attestation checked with `gh`, or a
manifest that is listed without a signature. The install on a host still
verifies the file against the pin; this shows the pin was not copied from a
tampered release.

A failure of any entry fails the run, an unreachable manifest included: a pin
that could not be compared has not been shown to be the publisher's.

Needs `gpg` for signed entries, and `gh` with GH_TOKEN set for attested ones.
Standard library only.

Usage (from tools/): python -m ci.checksums.verify [ENTRY ...]
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import IO, Any

from ci import proc
from ci.checksums import gpg, manifest, pins
from ci.checksums.registry import ENTRIES, Attested, Entry, Listed, Signed, Unchecked

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_LIMIT = 1 << 20
DOWNLOAD_LIMIT = 256 << 20
_HTTP_ERRORS = (urllib.error.URLError, TimeoutError, OSError)


class FetchError(Exception):
    """A publisher's file could not be fetched."""


Fetch = Callable[[str], bytes]
Download = Callable[[str, Path], str]  # (url, where to write) -> sha256 of what was written


class Http:
    """Plain GETs to a publisher: https only, redirects included, retried on a 429, a 5xx or a network error.

    Anything else, a 404 included, is final. `schemes` is widened only by tests, to reach a local server.
    """

    def __init__(self, schemes: tuple[str, ...] = ("https",), attempts: int = 3, sleep: Callable[[float], None] = time.sleep) -> None:
        self.schemes = schemes
        self.attempts = attempts
        self.sleep = sleep
        schemes_allowed = schemes

        class Redirects(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                if urllib.parse.urlparse(newurl).scheme not in schemes_allowed:
                    raise FetchError(f"{req.full_url} redirected to {newurl}, which is not {' or '.join(schemes_allowed)}")
                return super().redirect_request(req, fp, code, msg, headers, newurl)

        self._opener = urllib.request.build_opener(Redirects)

    def _get(self, url: str, consume: Callable[[IO[bytes]], Any]) -> Any:
        if urllib.parse.urlparse(url).scheme not in self.schemes:
            raise FetchError(f"refusing to fetch {url}: not {' or '.join(self.schemes)}")
        request = urllib.request.Request(url, headers={"User-Agent": "homelab-checksum-check"})  # noqa: S310 - scheme checked just above
        last = ""
        for attempt in range(self.attempts):
            if attempt:
                self.sleep(2.0**attempt)
            try:
                with self._opener.open(request, timeout=30) as reply:
                    return consume(reply)
            except urllib.error.HTTPError as exc:
                if exc.code != 429 and exc.code < 500:
                    raise FetchError(f"{url}: HTTP {exc.code}") from exc
                last = f"HTTP {exc.code}"
            except _HTTP_ERRORS as exc:
                last = str(exc)
        raise FetchError(f"{url}: {last} after {self.attempts} attempts")

    def fetch(self, url: str) -> bytes:
        def read(reply: IO[bytes]) -> bytes:
            body = reply.read(MANIFEST_LIMIT + 1)
            if len(body) > MANIFEST_LIMIT:
                raise FetchError(f"{url}: larger than {MANIFEST_LIMIT} bytes")
            return body

        return self._get(url, read)

    def download(self, url: str, dest: Path) -> str:
        def write(reply: IO[bytes]) -> str:
            digest, size = sha256(), 0
            with dest.open("wb") as out:
                while chunk := reply.read(1 << 20):
                    size += len(chunk)
                    if size > DOWNLOAD_LIMIT:
                        raise FetchError(f"{url}: larger than {DOWNLOAD_LIMIT} bytes")
                    digest.update(chunk)
                    out.write(chunk)
            return digest.hexdigest()

        return self._get(url, write)


@dataclass(frozen=True)
class Outcome:
    entry: Entry
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def _check_signed(root: Path, entry: Signed, version: str, pin: str, fetch: Fetch, run: proc.Runner) -> list[str]:
    signature = fetch(entry.signature_url.format(version=version)) if entry.signature_url else None
    text = gpg.verify_manifest(root / entry.key, entry.fingerprint, fetch(entry.manifest_url.format(version=version)), signature, run)
    problem = manifest.mismatch(manifest.parse(text), entry.file.format(version=version), pin)
    return [problem] if problem else []


def _check_listed(entry: Listed, version: str, pin: str, fetch: Fetch) -> list[str]:
    listed = manifest.parse(fetch(entry.manifest_url.format(version=version)).decode(errors="replace"))
    problem = manifest.mismatch(listed, entry.file.format(version=version), pin)
    return [problem] if problem else []


def _check_attested(entry: Attested, version: str, pin: str, download: Download, run: proc.Runner, workdir: Path) -> list[str]:
    url = entry.artifact_url.format(version=version)
    artifact = workdir / url.rsplit("/", 1)[-1]
    downloaded = download(url, artifact)
    if downloaded != pin:
        return [f"{artifact.name} hashes to {downloaded}, not the pin {pin}"]
    try:
        # gh prints nothing on success when it is not attached to a terminal, so the exit code is the whole answer.
        verified = run(["gh", "attestation", "verify", str(artifact), "--repo", entry.repository], workdir, True)
    except FileNotFoundError:
        return ["gh is not installed"]
    if verified.returncode != 0:
        return [f"gh attestation verify exited {verified.returncode} for {artifact.name} against {entry.repository}"]
    return []


def check_entry(root: Path, entry: Entry, fetch: Fetch, download: Download, run: proc.Runner, workdir: Path) -> Outcome:
    try:
        version, pin = pins.read_pin(root, entry)
        if isinstance(entry, Signed):
            errors = _check_signed(root, entry, version, pin, fetch, run)
        elif isinstance(entry, Attested):
            errors = _check_attested(entry, version, pin, download, run, workdir)
        elif isinstance(entry, Listed):
            errors = _check_listed(entry, version, pin, fetch)
        else:
            errors = []
    except (pins.PinError, FetchError, gpg.SignatureError) as exc:
        errors = [str(exc)]
    return Outcome(entry, errors)


def report(outcomes: list[Outcome]) -> tuple[list[str], int]:
    """(lines to print, exit code)."""
    lines = []
    for outcome in outcomes:
        entry = outcome.entry
        if isinstance(entry, Unchecked):
            lines.append(f"::notice::{entry.name} ({entry.pin.path}): no way to check this pin: {entry.reason}")
        for error in outcome.errors:
            lines.append(f"::error::{entry.name} ({entry.pin.path}): {error}")
    failed = [outcome for outcome in outcomes if not outcome.ok]
    lines.append(
        f"{len(outcomes)} pins: {len(outcomes) - len(failed)} passed, {len(failed)} failed ("
        + ", ".join(f"{outcome.entry.name} [{outcome.entry.tier.value}]{'' if outcome.ok else ' FAILED'}" for outcome in outcomes)
        + ")"
    )
    return lines, 1 if failed else 0


def main(
    argv: list[str] | None = None,
    root: Path = REPO_ROOT,
    entries: tuple[Entry, ...] = ENTRIES,
    http: Http | None = None,
    run: proc.Runner = proc.run,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("names", nargs="*", metavar="ENTRY", help="check only these entries")
    args = parser.parse_args(argv)
    unknown = sorted(set(args.names) - {entry.name for entry in entries})
    if unknown:
        parser.error(f"no registry entry named {', '.join(unknown)}")
    chosen = [entry for entry in entries if not args.names or entry.name in args.names]
    client = http or Http()
    outcomes = []
    for entry in chosen:
        with tempfile.TemporaryDirectory(prefix="checksum-") as workdir:
            outcomes.append(check_entry(root, entry, client.fetch, client.download, run, Path(workdir)))
    lines, code = report(outcomes)
    print("\n".join(lines))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as fh:
            fh.write("### Release checksums\n\n" + "\n".join(f"- {line}" for line in lines) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
