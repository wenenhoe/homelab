"""Tests for ci.checksums.verify.

A signed entry is checked with real gpg and keys generated per test. An attested
entry runs `gh` through a double bound to ci.proc.run's signature, since the
real one needs GitHub. HTTP is exercised against a local server, and every
other test serves its files from a dictionary. Nothing here reaches a real
publisher; a run against the real ones is the workflow's.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import hashlib
import http.server
import re
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from unittest.mock import create_autospec

import pytest
from ci import proc
from ci.checksums import verify
from ci.checksums.registry import Attested, Listed, Location, Signed, Unchecked

VERSION = "1.2.3"
FILE = f"tool-{VERSION}.zip"
OTHER_HASH = "b" * 64
MANIFEST_URL = f"https://example.invalid/{VERSION}/SHA256SUMS"
SIGNATURE_URL = f"https://example.invalid/{VERSION}/SHA256SUMS.sig"
ARTIFACT_URL = f"https://example.invalid/{VERSION}/tool.tar.gz"
ARTIFACT = b"the release tarball"
ARTIFACT_HASH = hashlib.sha256(ARTIFACT).hexdigest()
WHERE = {"pin": Location("defaults.yaml", "tool_sha256"), "version": Location("defaults.yaml", "tool_version")}


class Publisher:
    """Serves files from a dictionary and keeps the addresses it was asked for. Anything else is a 404."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.asked: list[str] = []

    def fetch(self, url: str) -> bytes:
        self.asked.append(url)
        if url not in self.files:
            raise verify.FetchError(f"{url}: HTTP 404")
        return self.files[url]

    def download(self, url: str, dest: Path) -> str:
        body = self.fetch(url)
        dest.write_bytes(body)
        return hashlib.sha256(body).hexdigest()


def tree(root: Path, pin: str, version: str = VERSION) -> Path:
    (root / "defaults.yaml").write_text(f'---\ntool_version: "{version}"\ntool_sha256: "{pin}"\n')
    return root


def commit_key(root: Path, signer) -> None:
    (root / "keys").mkdir(exist_ok=True)
    (root / "keys/tool.asc").write_bytes(signer.public_key())


def signed_entry(signer, detached: bool = False) -> Signed:
    return Signed(
        name="tool",
        file="tool-{version}.zip",
        manifest_url="https://example.invalid/{version}/SHA256SUMS",
        signature_url="https://example.invalid/{version}/SHA256SUMS.sig" if detached else None,
        fingerprint=signer.fingerprint,
        key="keys/tool.asc",
        **WHERE,
    )


def manifest_listing(pin: str) -> str:
    return f"{pin}  {FILE}\n{OTHER_HASH}  other-{VERSION}.zip\n"


def listed_entry() -> Listed:
    return Listed(name="tool", file="tool-{version}.zip", manifest_url="https://example.invalid/{version}/SHA256SUMS", **WHERE)


def attested_entry(repository: str = "owner/tool") -> Attested:
    return Attested(name="tool", artifact_url="https://example.invalid/{version}/tool.tar.gz", repository=repository, **WHERE)


def failure(outcome: verify.Outcome) -> str:
    """The one error an entry failed with. gpg's own verdict is matched by the keyword that matters, as its other keywords vary by version."""
    assert len(outcome.errors) == 1
    return outcome.errors[0]


def check(root: Path, entry, publisher: Publisher, run: proc.Runner = proc.run) -> verify.Outcome:
    workdir = root / "work"
    workdir.mkdir(exist_ok=True)
    return verify.check_entry(root, entry, publisher.fetch, publisher.download, run, workdir)


class TestSignedManifest:
    """A manifest clearsigned in place, as rclone publishes its."""

    PIN = "a" * 64

    def test_a_pin_equal_to_the_signed_line_passes(self, root, signer):
        commit_key(root, signer)
        publisher = Publisher({MANIFEST_URL: signer.clearsign(manifest_listing(self.PIN))})
        assert check(tree(root, self.PIN), signed_entry(signer), publisher).errors == []

    def test_a_pin_that_differs_from_the_signed_line_fails_and_names_the_signed_hash(self, root, signer):
        commit_key(root, signer)
        publisher = Publisher({MANIFEST_URL: signer.clearsign(manifest_listing(OTHER_HASH))})
        assert check(tree(root, self.PIN), signed_entry(signer), publisher).errors == [f"the pin is {self.PIN} but the manifest lists {OTHER_HASH} for {FILE}"]

    def test_a_pin_the_manifest_does_not_list_fails(self, root, signer):
        commit_key(root, signer)
        publisher = Publisher({MANIFEST_URL: signer.clearsign(f"{self.PIN}  something-else.zip\n")})
        assert check(tree(root, self.PIN), signed_entry(signer), publisher).errors == [f"the manifest has no line for {FILE}"]

    def test_a_manifest_altered_after_signing_fails(self, root, signer):
        commit_key(root, signer)
        altered = signer.clearsign(manifest_listing(OTHER_HASH)).replace(OTHER_HASH.encode(), self.PIN.encode())
        outcome = check(tree(root, self.PIN), signed_entry(signer), Publisher({MANIFEST_URL: altered}))
        assert failure(outcome).startswith("gpg reports") and "BADSIG" in failure(outcome)

    def test_a_manifest_signed_by_another_key_fails(self, root, signer, make_signer):
        commit_key(root, signer)
        forged = make_signer("Forger").clearsign(manifest_listing(self.PIN))
        outcome = check(tree(root, self.PIN), signed_entry(signer), Publisher({MANIFEST_URL: forged}))
        assert "NO_PUBKEY" in failure(outcome)

    def test_a_manifest_that_carries_no_signature_fails(self, root, signer):
        commit_key(root, signer)
        outcome = check(tree(root, self.PIN), signed_entry(signer), Publisher({MANIFEST_URL: manifest_listing(self.PIN).encode()}))
        assert "NODATA" in failure(outcome)

    def test_an_unreachable_manifest_fails_the_entry(self, root, signer):
        commit_key(root, signer)
        outcome = check(tree(root, self.PIN), signed_entry(signer), Publisher({}))
        assert outcome.errors == [f"{MANIFEST_URL}: HTTP 404"]

    def test_a_key_that_is_not_committed_fails_the_entry(self, root, signer):
        outcome = check(tree(root, self.PIN), signed_entry(signer), Publisher({MANIFEST_URL: signer.clearsign(manifest_listing(self.PIN))}))
        assert outcome.errors == ["the key file tool.asc is not committed"]

    def test_only_the_manifest_is_fetched_and_never_a_key(self, root, signer):
        commit_key(root, signer)
        publisher = Publisher({MANIFEST_URL: signer.clearsign(manifest_listing(self.PIN))})
        check(tree(root, self.PIN), signed_entry(signer), publisher)
        assert publisher.asked == [MANIFEST_URL]

    def test_the_version_pinned_in_the_repository_is_the_one_asked_for(self, root, signer):
        commit_key(root, signer)
        url = "https://example.invalid/9.9.9/SHA256SUMS"
        publisher = Publisher({url: signer.clearsign(f"{self.PIN}  tool-9.9.9.zip\n")})
        assert check(tree(root, self.PIN, version="9.9.9"), signed_entry(signer), publisher).errors == []
        assert publisher.asked == [url]


class TestSignedWithDetachedSignature:
    """A manifest and a signature published beside it, as OpenBao publishes its."""

    PIN = "a" * 64

    def test_a_pin_equal_to_the_signed_line_passes(self, root, signer):
        commit_key(root, signer)
        manifest = manifest_listing(self.PIN).encode()
        publisher = Publisher({MANIFEST_URL: manifest, SIGNATURE_URL: signer.detach(manifest)})
        assert check(tree(root, self.PIN), signed_entry(signer, detached=True), publisher).errors == []
        assert sorted(publisher.asked) == sorted([MANIFEST_URL, SIGNATURE_URL])

    def test_a_missing_signature_fails_even_though_the_manifest_lists_the_pin(self, root, signer):
        commit_key(root, signer)
        publisher = Publisher({MANIFEST_URL: manifest_listing(self.PIN).encode()})
        assert check(tree(root, self.PIN), signed_entry(signer, detached=True), publisher).errors == [f"{SIGNATURE_URL}: HTTP 404"]

    def test_a_signature_by_another_key_fails(self, root, signer, make_signer):
        commit_key(root, signer)
        manifest = manifest_listing(self.PIN).encode()
        publisher = Publisher({MANIFEST_URL: manifest, SIGNATURE_URL: make_signer("Forger").detach(manifest)})
        assert "NO_PUBKEY" in failure(check(tree(root, self.PIN), signed_entry(signer, detached=True), publisher))

    def test_a_manifest_changed_after_it_was_signed_fails(self, root, signer):
        commit_key(root, signer)
        genuine = manifest_listing(OTHER_HASH).encode()
        tampered = manifest_listing(self.PIN).encode()
        publisher = Publisher({MANIFEST_URL: tampered, SIGNATURE_URL: signer.detach(genuine)})
        assert "BADSIG" in failure(check(tree(root, self.PIN), signed_entry(signer, detached=True), publisher))


class TestListedManifest:
    PIN = "a" * 64

    def test_a_pin_equal_to_the_listed_hash_passes(self, root):
        publisher = Publisher({MANIFEST_URL: manifest_listing(self.PIN).encode()})
        assert check(tree(root, self.PIN), listed_entry(), publisher).errors == []

    def test_a_name_written_with_a_leading_dot_slash_is_the_same_file(self, root):
        publisher = Publisher({MANIFEST_URL: f"{self.PIN}  ./{FILE}\n".encode()})
        assert check(tree(root, self.PIN), listed_entry(), publisher).errors == []

    def test_a_pin_that_differs_names_the_listed_hash_so_it_can_be_copied(self, root):
        publisher = Publisher({MANIFEST_URL: manifest_listing(OTHER_HASH).encode()})
        assert check(tree(root, self.PIN), listed_entry(), publisher).errors == [f"the pin is {self.PIN} but the manifest lists {OTHER_HASH} for {FILE}"]

    def test_a_pin_absent_from_the_manifest_fails(self, root):
        publisher = Publisher({MANIFEST_URL: f"{self.PIN}  another-file.zip\n".encode()})
        assert check(tree(root, self.PIN), listed_entry(), publisher).errors == [f"the manifest has no line for {FILE}"]

    def test_an_unreachable_manifest_fails_the_entry(self, root):
        assert check(tree(root, self.PIN), listed_entry(), Publisher({})).errors == [f"{MANIFEST_URL}: HTTP 404"]


class TestAttestedArtifact:
    """`gh attestation verify` is the double; its real exit status is the verdict."""

    @staticmethod
    def gh(returncode: int = 0):
        return create_autospec(proc.run, return_value=subprocess.CompletedProcess([], returncode, stdout=""))

    @staticmethod
    def gh_that_attests_only(repository: str):
        """Exits 0 only for the repository that built the artifact, as the real command does."""

        def run(args: list[str], cwd: Path, capture: bool = False) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args, 0 if args[args.index("--repo") + 1] == repository else 1, stdout="")

        return create_autospec(proc.run, side_effect=run)

    def test_a_download_that_hashes_to_the_pin_and_passes_gh_passes(self, root):
        run = self.gh()
        assert check(tree(root, ARTIFACT_HASH), attested_entry(), Publisher({ARTIFACT_URL: ARTIFACT}), run).errors == []
        run.assert_called_once_with(["gh", "attestation", "verify", str(root / "work/tool.tar.gz"), "--repo", "owner/tool"], root / "work", True)

    def test_a_failing_exit_from_gh_fails_the_entry(self, root):
        outcome = check(tree(root, ARTIFACT_HASH), attested_entry(), Publisher({ARTIFACT_URL: ARTIFACT}), self.gh(returncode=1))
        assert outcome.errors == ["gh attestation verify exited 1 for tool.tar.gz against owner/tool"]

    def test_a_download_that_does_not_hash_to_the_pin_fails_without_asking_gh(self, root):
        run = self.gh()
        outcome = check(tree(root, OTHER_HASH), attested_entry(), Publisher({ARTIFACT_URL: ARTIFACT}), run)
        assert outcome.errors == [f"tool.tar.gz hashes to {ARTIFACT_HASH}, not the pin {OTHER_HASH}"]
        run.assert_not_called()

    def test_an_artifact_attested_for_another_repository_fails(self, root):
        run = self.gh_that_attests_only("owner/tool")
        publisher = Publisher({ARTIFACT_URL: ARTIFACT})
        assert check(tree(root, ARTIFACT_HASH), attested_entry("owner/tool"), publisher, run).errors == []
        wrong = check(tree(root, ARTIFACT_HASH), attested_entry("someone/else"), publisher, run)
        assert wrong.errors == ["gh attestation verify exited 1 for tool.tar.gz against someone/else"]

    def test_a_missing_gh_fails_the_entry(self, root):
        run = create_autospec(proc.run, side_effect=FileNotFoundError("gh"))
        outcome = check(tree(root, ARTIFACT_HASH), attested_entry(), Publisher({ARTIFACT_URL: ARTIFACT}), run)
        assert outcome.errors == ["gh is not installed"]

    def test_an_artifact_that_cannot_be_downloaded_fails_the_entry(self, root):
        run = self.gh()
        assert check(tree(root, ARTIFACT_HASH), attested_entry(), Publisher({}), run).errors == [f"{ARTIFACT_URL}: HTTP 404"]
        run.assert_not_called()


class TestUncheckedAndPinProblems:
    def test_an_artifact_with_nothing_to_check_it_against_passes_and_is_reported_as_such(self, root):
        entry = Unchecked(name="tool", reason="the publisher lists no hash", **WHERE)
        publisher = Publisher({})
        outcome = check(tree(root, "a" * 64), entry, publisher)
        assert (outcome.errors, publisher.asked) == ([], [])
        lines, code = verify.report([outcome])
        assert (lines[0], code) == ("::notice::tool (defaults.yaml): no way to check this pin: the publisher lists no hash", 0)

    def test_a_pin_that_cannot_be_read_fails_the_entry(self, root):
        (root / "defaults.yaml").write_text("tool_version: 1.2.3\n")
        outcome = check(root, listed_entry(), Publisher({}))
        assert outcome.errors == ["defaults.yaml has no tool_sha256 set to a plain value"]

    def test_a_version_that_could_redirect_a_download_is_refused_before_any_request(self, root):
        publisher = Publisher({})
        outcome = check(tree(root, "a" * 64, version="1.2.3/../../x"), listed_entry(), publisher)
        assert (outcome.errors, publisher.asked) == (["tool_version in defaults.yaml is '1.2.3/../../x', which isn't a release version"], [])


class TestReport:
    def test_every_pass_exits_zero_and_the_summary_names_each_entrys_tier(self, root):
        lines, code = verify.report([verify.Outcome(listed_entry(), [])])
        assert (lines, code) == (["1 pins: 1 passed, 0 failed (tool [listed])"], 0)

    def test_a_failure_is_an_error_annotation_and_fails_the_run(self):
        lines, code = verify.report([verify.Outcome(listed_entry(), ["the manifest has no line for x"])])
        assert lines == ["::error::tool (defaults.yaml): the manifest has no line for x", "1 pins: 0 passed, 1 failed (tool [listed] FAILED)"]
        assert code == 1

    def test_one_failure_among_passes_still_fails_the_run(self):
        other = Listed(name="other", file="o.zip", manifest_url="https://example.invalid/o", **WHERE)
        _, code = verify.report([verify.Outcome(other, []), verify.Outcome(listed_entry(), ["boom"])])
        assert code == 1


class FakeHttp:
    """Stands in for verify.Http in main: the publisher's files, served from a dictionary."""

    def __init__(self, publisher: Publisher) -> None:
        self.fetch = publisher.fetch
        self.download = publisher.download


class TestMain:
    PIN = "a" * 64

    def run_main(self, root: Path, entries, files: dict[str, bytes], *names: str, run: proc.Runner = proc.run) -> int:
        return verify.main(list(names), root=root, entries=tuple(entries), http=FakeHttp(Publisher(files)), run=run)  # type: ignore[arg-type]

    def test_a_run_where_every_pin_checks_out_exits_zero(self, root, capsys):
        code = self.run_main(tree(root, self.PIN), [listed_entry()], {MANIFEST_URL: manifest_listing(self.PIN).encode()})
        assert (code, capsys.readouterr().out.strip()) == (0, "1 pins: 1 passed, 0 failed (tool [listed])")

    def test_a_pin_that_does_not_check_out_exits_non_zero_and_says_which(self, root, capsys):
        code = self.run_main(tree(root, self.PIN), [listed_entry()], {MANIFEST_URL: manifest_listing(OTHER_HASH).encode()})
        assert code == 1
        assert f"::error::tool (defaults.yaml): the pin is {self.PIN} but the manifest lists {OTHER_HASH} for {FILE}" in capsys.readouterr().out

    def test_every_entry_is_checked_even_after_one_fails(self, root, capsys):
        second = Listed(name="second", file="second.zip", manifest_url="https://example.invalid/second", **WHERE)
        files = {MANIFEST_URL: manifest_listing(OTHER_HASH).encode(), "https://example.invalid/second": f"{self.PIN}  second.zip\n".encode()}
        code = self.run_main(tree(root, self.PIN), [listed_entry(), second], files)
        assert code == 1
        assert "2 pins: 1 passed, 1 failed (tool [listed] FAILED, second [listed])" in capsys.readouterr().out

    def test_named_entries_are_the_only_ones_checked(self, root, capsys):
        second = Listed(name="second", file="second.zip", manifest_url="https://example.invalid/second", **WHERE)
        code = self.run_main(tree(root, self.PIN), [listed_entry(), second], {"https://example.invalid/second": f"{self.PIN}  second.zip\n".encode()}, "second")
        assert (code, capsys.readouterr().out.strip()) == (0, "1 pins: 1 passed, 0 failed (second [listed])")

    def test_an_entry_that_is_not_in_the_registry_is_a_usage_error(self, root, capsys):
        with pytest.raises(SystemExit) as stopped:
            self.run_main(tree(root, self.PIN), [listed_entry()], {}, "nothing")
        assert stopped.value.code == 2
        assert "no registry entry named nothing" in capsys.readouterr().err

    def test_the_run_is_written_to_the_step_summary_when_running_in_actions(self, root, monkeypatch):
        summary = root / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
        self.run_main(tree(root, self.PIN), [listed_entry()], {MANIFEST_URL: manifest_listing(self.PIN).encode()})
        assert summary.read_text() == "### Release checksums\n\n- 1 pins: 1 passed, 0 failed (tool [listed])\n"


class Site:
    """A local HTTP server. `routes` maps a path to replies served in order, the last one repeating."""

    def __init__(self) -> None:
        self.routes: dict[str, list[tuple[int, dict[str, str], bytes]]] = {}
        self.requests: list[str] = []
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):  # silence the server
                pass

            def do_GET(self):
                owner.requests.append(self.path)
                queue = owner.routes.get(self.path)
                status, headers, body = (queue.pop(0) if len(queue) > 1 else queue[0]) if queue else (404, {}, b"")
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True).start()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def site():
    server = Site()
    yield server
    server.close()


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def http_client(sleeps) -> Callable[..., verify.Http]:
    return lambda **kwargs: verify.Http(schemes=("http",), sleep=sleeps.append, **kwargs)


class TestHttp:
    def test_a_body_is_returned_whole(self, site, http_client):
        site.routes["/m"] = [(200, {}, b"manifest text")]
        assert http_client().fetch(site.url("/m")) == b"manifest text"

    def test_a_404_is_final_and_asked_once(self, site, http_client, sleeps):
        with pytest.raises(verify.FetchError, match="HTTP 404"):
            http_client().fetch(site.url("/gone"))
        assert (site.requests, sleeps) == (["/gone"], [])

    @pytest.mark.parametrize("status", [pytest.param(429, id="rate-limited"), pytest.param(500, id="server-error"), pytest.param(503, id="unavailable")])
    def test_a_throttled_or_failing_server_is_asked_again(self, site, http_client, sleeps, status):
        site.routes["/m"] = [(status, {}, b""), (200, {}, b"ok")]
        assert http_client().fetch(site.url("/m")) == b"ok"
        assert (len(site.requests), sleeps) == (2, [2.0])

    def test_a_server_that_keeps_failing_fails_the_fetch_after_the_attempts_it_is_given(self, site, http_client, sleeps):
        site.routes["/m"] = [(503, {}, b"")]
        with pytest.raises(verify.FetchError, match="HTTP 503 after 3 attempts"):
            http_client().fetch(site.url("/m"))
        assert (len(site.requests), sleeps) == (3, [2.0, 4.0])

    def test_a_server_that_cannot_be_reached_fails_the_fetch_after_the_attempts_it_is_given(self, site, http_client, sleeps):
        url = site.url("/m")
        site.close()
        with pytest.raises(verify.FetchError, match="after 3 attempts"):
            http_client().fetch(url)
        assert sleeps == [2.0, 4.0]

    def test_a_body_over_the_limit_is_refused(self, site, http_client, monkeypatch):
        monkeypatch.setattr(verify, "MANIFEST_LIMIT", 8)
        site.routes["/m"] = [(200, {}, b"123456789")]
        with pytest.raises(verify.FetchError, match="larger than 8 bytes"):
            http_client().fetch(site.url("/m"))

    def test_a_redirect_is_followed_within_the_allowed_schemes(self, site, http_client):
        site.routes["/old"] = [(302, {"Location": site.url("/new")}, b"")]
        site.routes["/new"] = [(200, {}, b"moved")]
        assert http_client().fetch(site.url("/old")) == b"moved"

    def test_a_redirect_to_a_scheme_that_is_not_allowed_is_refused(self, site, http_client):
        site.routes["/old"] = [(302, {"Location": "https://elsewhere.invalid/new"}, b"")]
        with pytest.raises(verify.FetchError, match=re.escape("redirected to https://elsewhere.invalid/new, which is not http")):
            http_client().fetch(site.url("/old"))

    def test_plain_http_is_refused_by_default_and_nothing_is_sent(self, site):
        with pytest.raises(verify.FetchError, match=r"refusing to fetch .* not https"):
            verify.Http().fetch(site.url("/m"))
        assert site.requests == []

    def test_a_download_is_written_to_disk_and_its_sha256_returned(self, site, http_client, root):
        site.routes["/a"] = [(200, {}, ARTIFACT)]
        assert http_client().download(site.url("/a"), root / "a.bin") == ARTIFACT_HASH
        assert (root / "a.bin").read_bytes() == ARTIFACT

    def test_a_download_over_the_limit_is_refused(self, site, http_client, root, monkeypatch):
        monkeypatch.setattr(verify, "DOWNLOAD_LIMIT", 4)
        site.routes["/a"] = [(200, {}, ARTIFACT)]
        with pytest.raises(verify.FetchError, match="larger than 4 bytes"):
            http_client().download(site.url("/a"), root / "a.bin")
