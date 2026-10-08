#!/usr/bin/env python3
"""Does every container image this repo pins still exist in its registry?

check-pins (ci.images.registry) is an offline, per-PR check on the images this
repo builds. This is the other half, run weekly: it collects every image
reference the repo pins, wherever it pins it, and asks the registry whether
the tag is still there. Renovate only ever proposes tags that exist, so a tag
an upstream later removes or renames is invisible to it; it shows up here
instead of as a failed deploy.

Where references come from (nothing is listed by hand):

- `image:` lines in compose files and in Ansible YAML/templates, which covers
  the docker/ stacks, Molecule scenarios and fixtures, and task arguments;
- `FROM` and `COPY --from=<image>` in Dockerfiles, skipping build stages;
- every Renovate `customManagers` entry with `datasourceTemplate: "docker"`
  in .github/renovate.json5, applied to the files it names: the pins that sit
  in a systemd unit, a shell script or a variable default. If one of those
  managers no longer matches any file or any text, the pin moved out from
  under it and this check can't see it, so that is reported as a failure.

Skipped, and listed in the output: a reference with a template or variable in
it, `scratch`, a build stage, and a `:local` tag (built on the host, never
pushed).

It speaks the standard registry API with the standard library, one HEAD request
per distinct image (a HEAD doesn't download the image), and works out the
anonymous token endpoint from the registry's own 401 challenge, so Docker Hub,
ghcr.io and any other v2 registry take the same path.

Rate limiting is the main risk, so it is deliberately gentle: one request at a
time with a pause between them, a token cached per repository, a 429 or 5xx
retried with backoff (honouring Retry-After), and a second pass after a
cooldown for whatever stayed unanswered. An image whose registry never
answered is a warning, not a failure; only a tag the registry says isn't
there, or a Renovate manager that lost its file, fails the run.

Usage (from tools/): python -m ci.images.remote {list [--json]|check}
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from ci import json5

REPO_ROOT = Path(__file__).resolve().parents[3]
RENOVATE_CONFIG = ".github/renovate.json5"
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache"}
MANIFEST_TYPES = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)

_IMAGE_LINE = re.compile(r"""^\s*(?:-\s+)?image:\s*["']?([^\s"'#]+)""", re.MULTILINE)
_FROM = re.compile(r"^\s*FROM\s+(?:--\S+\s+)*(\S+)(?:\s+AS\s+(\S+))?\s*$", re.IGNORECASE)
_COPY_FROM = re.compile(r"^\s*COPY\s+(?:--\S+\s+)*--from=(\S+)", re.IGNORECASE)
_CHALLENGE_PARAM = re.compile(r'(\w+)="([^"]*)"')
_JS_NAMED_GROUP = re.compile(r"\(\?<(?![=!])(\w+)>")
_DOCKER_HUB = "registry-1.docker.io"
# Named, not written inline: `ruff format` targets 3.14 and drops the parentheses from a bare
# `except (A, B):`, which older Pythons (the runner's python3) can't parse.
_READ_ERRORS = (OSError, UnicodeDecodeError)
_CONFIG_ERRORS = (OSError, json5.Json5Error)
_HTTP_ERRORS = (urllib.error.URLError, TimeoutError, OSError)


class RemoteError(Exception):
    """Something needed to build the list of images is wrong."""


@dataclass(frozen=True)
class Ref:
    text: str  # as written: name[:tag][@digest]
    source: str  # repo-relative file it was found in


@dataclass(frozen=True)
class Image:
    registry: str  # host to ask (Docker Hub is registry-1.docker.io)
    repository: str
    reference: str  # a tag, or a digest when one is pinned

    def __str__(self) -> str:
        return f"{self.registry}/{self.repository}{'@' if self.reference.startswith('sha256:') else ':'}{self.reference}"


def parse_image(text: str) -> Image:
    """`[registry/]name[:tag][@digest]` -> where to ask and what to ask for."""
    remainder, _, digest = text.partition("@")
    head, sep, tail = remainder.rpartition(":")
    name, tag = (head, tail) if sep and "/" not in tail else (remainder, "")
    first, slash, rest = name.partition("/")
    if slash and ("." in first or ":" in first or first == "localhost"):
        registry, repository = first, rest
    else:
        registry, repository = _DOCKER_HUB, name if slash else f"library/{name}"
    if not name or not repository.strip("/") or repository.endswith("/") or any(c.isspace() for c in text):
        raise ValueError(f"not an image reference: {text!r}")
    return Image(registry, repository, digest or tag or "latest")


def skip_reason(text: str) -> str | None:
    if not text:
        return "empty"
    if any(marker in text for marker in ("{{", "{%", "${", "$(")) or text.startswith("$"):
        return "templated"
    if text == "scratch":
        return "scratch"
    if text.rpartition(":")[2] == "local" and ":" in text:
        return "built locally"
    return None


def _walk(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            yield Path(dirpath) / name


def _text(path: Path) -> str | None:
    try:
        return path.read_text()
    except _READ_ERRORS:
        return None


def _is_yaml_like(rel: str) -> bool:
    if rel.startswith(("docker/", "ansible/", ".github/workflows/", ".github/actions/")):
        return rel.endswith((".yml", ".yaml", ".yml.j2", ".yaml.j2", ".j2"))
    return False


def standard_refs(root: Path) -> list[Ref]:
    refs: list[Ref] = []
    for path in _walk(root):
        rel = path.relative_to(root).as_posix()
        if path.name == "Dockerfile" and rel.startswith(("docker/", "tools/")):
            text = _text(path)
            if text is not None:
                refs += _dockerfile_refs(text, rel)
        elif _is_yaml_like(rel):
            text = _text(path)
            if text is not None:
                refs += [Ref(m.group(1), rel) for m in _IMAGE_LINE.finditer(text)]
    return refs


def _dockerfile_refs(text: str, rel: str) -> list[Ref]:
    stages: set[str] = set()
    refs: list[Ref] = []
    for line in text.splitlines():
        if match := _FROM.match(line):
            image, alias = match.group(1), match.group(2)
            if image.lower() not in stages:
                refs.append(Ref(image, rel))
            if alias:
                stages.add(alias.lower())
        elif (match := _COPY_FROM.match(line)) and match.group(1).lower() not in stages and not match.group(1).isdigit():
            refs.append(Ref(match.group(1), rel))
    return refs


def _file_matcher(pattern: str) -> re.Pattern[str]:
    if len(pattern) < 2 or not (pattern.startswith("/") and pattern.endswith("/")):
        raise RemoteError(f"unsupported managerFilePatterns entry {pattern!r}: only /regex/ is handled")
    return re.compile(pattern[1:-1])


def renovate_refs(root: Path) -> tuple[list[Ref], list[str]]:
    """(references, problems) from the docker-datasource regex managers in renovate.json5."""
    path = root / RENOVATE_CONFIG
    try:
        config = json5.loads(path.read_text())
    except _CONFIG_ERRORS as exc:
        raise RemoteError(f"can't read {RENOVATE_CONFIG}: {exc}") from exc
    if not isinstance(config, dict):
        raise RemoteError(f"{RENOVATE_CONFIG} isn't an object")
    files = [(path.relative_to(root).as_posix(), path) for path in _walk(root)]
    refs: list[Ref] = []
    problems: list[str] = []
    for manager in config.get("customManagers", []):
        if manager.get("customType") != "regex" or manager.get("datasourceTemplate") != "docker":
            continue
        label = manager.get("description", "a custom manager")
        matchers = [_file_matcher(p) for p in manager.get("managerFilePatterns", [])]
        expressions = [re.compile(_JS_NAMED_GROUP.sub(r"(?P<\1>", s), re.MULTILINE) for s in manager.get("matchStrings", [])]
        targets = [(rel, file) for rel, file in files if any(m.search(rel) for m in matchers)]
        if not targets:
            problems.append(f"Renovate manager matches no file, so its pin moved or was removed: {label}")
            continue
        for rel, file in targets:
            text = _text(file) or ""
            found = 0
            for expression in expressions:
                for match in expression.finditer(text):
                    groups = match.groupdict()
                    name = groups.get("depName") or manager.get("depNameTemplate")
                    value = groups.get("currentValue")
                    if not name or not value:
                        raise RemoteError(f"{RENOVATE_CONFIG}: a docker manager must yield a depName and currentValue: {label}")
                    refs.append(Ref(f"{name}:{value}", rel))
                    found += 1
            if not found:
                problems.append(f"{rel}: no longer matches the Renovate manager that tracks it ({label})")
    return refs, problems


@dataclass
class Collected:
    images: dict[str, list[str]] = field(default_factory=dict)  # reference text -> files naming it
    skipped: dict[str, str] = field(default_factory=dict)  # reference text -> why
    problems: list[str] = field(default_factory=list)


def collect(root: Path) -> Collected:
    collected = Collected()
    renovate, collected.problems = renovate_refs(root)
    for ref in [*standard_refs(root), *renovate]:
        reason = skip_reason(ref.text)
        if reason:
            collected.skipped[ref.text] = reason
        else:
            files = collected.images.setdefault(ref.text, [])
            if ref.source not in files:
                files.append(ref.source)
    return collected


INVENTORY_VERSION = 1


def inventory(collected: Collected) -> dict[str, object]:
    """The document `list --json` prints; docs/topics/engineering/ci/image-tag-check.md defines its shape."""
    return {
        "version": INVENTORY_VERSION,
        "images": [{"ref": text, "sources": sorted(files)} for text, files in sorted(collected.images.items())],
        "skipped": [{"ref": text, "reason": reason} for text, reason in sorted(collected.skipped.items())],
        "problems": list(collected.problems),
    }


class Verdict(Enum):
    OK = "ok"
    MISSING = "missing"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes = b""


class NetworkError(Exception):
    """No HTTP response at all: DNS, connection or timeout."""


Opener = Callable[[urllib.request.Request], Response]
BaseUrl = Callable[[str], str]


def open_url(request: urllib.request.Request) -> Response:
    try:
        with urllib.request.urlopen(request, timeout=20) as reply:  # noqa: S310 - https URLs to registries, built here
            return Response(reply.status, {k.lower(): v for k, v in reply.headers.items()}, reply.read() if request.get_method() == "GET" else b"")
    except urllib.error.HTTPError as exc:
        return Response(exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read() if request.get_method() == "GET" else b"")
    except _HTTP_ERRORS as exc:
        raise NetworkError(str(exc)) from exc


def https_base(registry: str) -> str:
    return f"https://{registry}"


class Registry:
    """Existence checks against v2 registries, gentle with them."""

    def __init__(
        self,
        opener: Opener = open_url,
        base_url: BaseUrl = https_base,
        sleep: Callable[[float], None] = time.sleep,
        delay: float = 0.5,
        attempts: int = 5,
        max_wait: float = 60.0,
        schemes: tuple[str, ...] = ("https",),
    ) -> None:
        self.opener = opener
        self.base_url = base_url
        self.sleep = sleep
        self.delay = delay
        self.attempts = attempts
        self.max_wait = max_wait
        self.schemes = schemes
        self.tokens: dict[tuple[str, str, str], str] = {}
        self.requests = 0

    def _request(self, url: str, method: str, headers: dict[str, str]) -> urllib.request.Request:
        if urllib.parse.urlparse(url).scheme not in self.schemes:
            raise NetworkError(f"refusing to fetch {url}: scheme not in {self.schemes}")
        return urllib.request.Request(url, method=method, headers=headers)  # noqa: S310 - scheme checked just above

    def _send(self, request: urllib.request.Request) -> Response:
        """One request, paced, retried on 429/5xx/network errors. Raises NetworkError if it never answers."""
        last: Response | NetworkError | None = None
        for attempt in range(self.attempts):
            if self.requests:
                self.sleep(self.delay)
            self.requests += 1
            try:
                response = self.opener(request)
            except NetworkError as exc:
                last, wait = exc, min(2.0 ** (attempt + 1), self.max_wait)
            else:
                if response.status != 429 and response.status < 500:
                    return response
                last, wait = response, self._wait(response, attempt)
            if attempt < self.attempts - 1:
                self.sleep(wait)
        if isinstance(last, NetworkError):
            raise last
        if last is None:  # attempts < 1: nothing was ever sent
            raise NetworkError("no request was attempted")
        return last

    def _wait(self, response: Response, attempt: int) -> float:
        header = response.headers.get("retry-after", "")
        try:
            return min(float(header), self.max_wait)
        except ValueError:
            return min(2.0 ** (attempt + 1), self.max_wait)

    def _token(self, challenge: str) -> str | None:
        params = dict(_CHALLENGE_PARAM.findall(challenge))
        realm = params.get("realm")
        if not challenge.lower().startswith("bearer") or not realm:
            return None
        key = (realm, params.get("service", ""), params.get("scope", ""))
        if key not in self.tokens:
            query = urllib.parse.urlencode({k: v for k, v in (("service", key[1]), ("scope", key[2])) if v})
            reply = self._send(self._request(f"{realm}?{query}" if query else realm, "GET", {"User-Agent": "homelab-image-check"}))
            if reply.status != 200:
                return None
            data = json.loads(reply.body or b"{}")
            self.tokens[key] = data.get("token") or data.get("access_token") or ""
        return self.tokens[key] or None

    def check(self, image: Image) -> tuple[Verdict, str]:
        url = f"{self.base_url(image.registry)}/v2/{image.repository}/manifests/{image.reference}"
        headers = {"Accept": MANIFEST_TYPES, "User-Agent": "homelab-image-check"}
        try:
            response = self._send(self._request(url, "HEAD", headers))
            if response.status == 401 and (token := self._token(response.headers.get("www-authenticate", ""))):
                response = self._send(self._request(url, "HEAD", {**headers, "Authorization": f"Bearer {token}"}))
        except NetworkError as exc:
            return Verdict.INCONCLUSIVE, f"no answer from {image.registry}: {exc}"
        if response.status == 200:
            return Verdict.OK, "found"
        if response.status == 404:
            return Verdict.MISSING, "the registry has no such tag"
        if response.status in (401, 403):
            return Verdict.MISSING, f"HTTP {response.status} anonymously: the tag or repository is gone, renamed or private"
        if response.status == 429 or response.status >= 500:
            return Verdict.INCONCLUSIVE, f"HTTP {response.status} from {image.registry} after {self.attempts} attempts"
        return Verdict.INCONCLUSIVE, f"unexpected HTTP {response.status} from {image.registry}"


def run_checks(collected: Collected, registry: Registry, sleep: Callable[[float], None] = time.sleep, cooldown: float = 60.0) -> dict[str, tuple[Verdict, str]]:
    """Check every image once; give the inconclusive ones a second pass after `cooldown`."""
    results: dict[str, tuple[Verdict, str]] = {}
    for text in collected.images:
        try:
            results[text] = registry.check(parse_image(text))
        except ValueError as exc:
            results[text] = (Verdict.MISSING, str(exc))
    unanswered = [text for text, (verdict, _) in results.items() if verdict is Verdict.INCONCLUSIVE]
    if unanswered:
        sleep(cooldown)
        for text in unanswered:
            results[text] = registry.check(parse_image(text))
    return results


def report(collected: Collected, results: dict[str, tuple[Verdict, str]]) -> tuple[list[str], int]:
    """(lines to print, exit code)."""
    lines: list[str] = []
    for problem in collected.problems:
        lines.append(f"::error::{problem}")
    for text, (verdict, detail) in sorted(results.items()):
        files = ", ".join(collected.images[text])
        if verdict is Verdict.MISSING:
            lines.append(f"::error::{text} ({files}): {detail}")
        elif verdict is Verdict.INCONCLUSIVE:
            lines.append(f"::warning::{text} ({files}): {detail}; not checked this run")
    counts = {v: sum(1 for verdict, _ in results.values() if verdict is v) for v in Verdict}
    lines.append(
        f"{len(results)} images: {counts[Verdict.OK]} found, {counts[Verdict.MISSING]} missing, {counts[Verdict.INCONCLUSIVE]} unanswered; "
        f"{len(collected.skipped)} skipped ({', '.join(f'{t} [{r}]' for t, r in sorted(collected.skipped.items())) or 'none'})"
    )
    return lines, 1 if counts[Verdict.MISSING] or collected.problems else 0


def main(argv: list[str] | None = None, registry: Registry | None = None, sleep: Callable[[float], None] = time.sleep) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["list", "check"])
    parser.add_argument("--json", action="store_true", help="with list: print the inventory as one JSON document")
    args = parser.parse_args(argv)
    if args.json and args.command != "list":
        parser.error("--json applies to list only")
    try:
        collected = collect(REPO_ROOT)
    except RemoteError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    if args.command == "list":
        if args.json:
            print(json.dumps(inventory(collected), indent=2))
            return 0
        for text, files in sorted(collected.images.items()):
            print(f"{text}  <- {', '.join(files)}")
        for problem in collected.problems:
            print(f"problem: {problem}")
        print(f"skipped: {collected.skipped}")
        return 0
    lines, code = report(collected, run_checks(collected, registry or Registry(), sleep))
    print("\n".join(lines))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as fh:
            fh.write("### Image tags\n\n" + "\n".join(f"- {line}" for line in lines) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
