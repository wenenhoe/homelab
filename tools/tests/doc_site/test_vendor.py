"""The vendored stylesheet is the file its pin names, and the pin is what the registry publishes."""

from __future__ import annotations

import io
import tarfile

import pytest
from doc_site import vendor

BODY = b"body{margin:0}"
ZERO = "0" * 64


def package(version: str, body: bytes = BODY, name: str = "package/simple.min.css") -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo(name)
        info.size = len(body)
        archive.addfile(info, io.BytesIO(body))
    return buffer.getvalue()


def registry(version: str = "2.3.7", body: bytes = BODY, tagged: bytes = BODY, urls: list[str] | None = None):
    """A fetch that serves the registry's tarball and the repository's tagged file."""

    def fetch(url: str) -> bytes:
        if urls is not None:
            urls.append(url)
        return tagged if url.startswith(vendor.RAW) else package(version, body)

    return fetch


@pytest.fixture
def vendored(tmp_path):
    folder = tmp_path / "vendor"
    folder.mkdir()
    (folder / "simple.min.css").write_bytes(BODY)
    pin = folder / "simple.pin"
    pin.write_text(
        "\n".join(
            ["package = simpledotcss", "version = 2.3.7", "file = simple.min.css", f"sha256 = {vendor.digest(BODY)}", "repository = kevquirk/simple.css", ""]
        ),
        encoding="utf-8",
    )
    return folder, pin


def test_the_committed_file_is_the_one_the_pin_names():
    assert vendor.local_errors() == []


def test_the_pin_is_one_line_for_each_of_four_keys():
    pin = vendor.read_pin()
    assert (pin.package, pin.file) == ("simpledotcss", "simple.min.css")


def test_a_changed_file_fails_the_check(vendored):
    folder, pin = vendored
    (folder / "simple.min.css").write_bytes(BODY + b" ")
    (error,) = vendor.local_errors(folder, pin)
    assert "sha256" in error


def test_a_missing_file_fails_the_check(vendored):
    folder, pin = vendored
    (folder / "simple.min.css").unlink()
    assert vendor.local_errors(folder, pin)


@pytest.mark.parametrize(
    "text",
    [
        "package = x\n",
        "package = a\nversion = 1\nfile = f\nsha256 = 0\nrepository = a/b\n",
        f"package = a\npackage = b\nversion = 1.0.0\nfile = f.css\nsha256 = {ZERO}\nrepository = a/b\n",
        f"package = a\nversion = 1.0.0\nfile = f.css\nsha256 = {ZERO}\nrepository = ../b\n",
        f"package = a\nversion = 1.0.0\nfile = f.css\nsha256 = {ZERO}\n",
    ],
)
def test_a_malformed_pin_is_refused(tmp_path, text):
    pin = tmp_path / "pin"
    pin.write_text(text, encoding="utf-8")
    with pytest.raises(vendor.VendorError):
        vendor.read_pin(pin)


def test_the_registry_file_is_compared_with_the_pin_and_the_file(vendored):
    folder, pin = vendored
    assert vendor.upstream_errors(registry(), folder, pin) == []
    assert len(vendor.upstream_errors(registry(body=b"other", tagged=b"other"), folder, pin)) == 2


def test_a_tarball_that_differs_from_the_tagged_source_fails(vendored):
    folder, pin = vendored
    (error,) = vendor.upstream_errors(registry(tagged=b"other"), folder, pin)
    assert "kevquirk/simple.css at v2.3.7" in error


def test_a_package_without_the_file_is_refused(vendored):
    folder, pin = vendored
    with pytest.raises(vendor.VendorError):
        vendor.upstream_errors(lambda url: package("2.3.7", name="package/other.css"), folder, pin)


def test_the_tarball_and_the_tagged_file_are_fetched_for_the_pinned_version(vendored):
    folder, pin = vendored
    urls: list[str] = []
    vendor.upstream_errors(registry(urls=urls), folder, pin)
    assert sorted(urls) == [
        "https://raw.githubusercontent.com/kevquirk/simple.css/v2.3.7/simple.min.css",
        "https://registry.npmjs.org/simpledotcss/-/simpledotcss-2.3.7.tgz",
    ]


def test_only_the_registry_and_the_raw_host_are_fetched():
    with pytest.raises(vendor.VendorError):
        vendor.http_fetch("https://example.com/x.tgz")


def test_update_replaces_the_file_and_the_pin_together(vendored):
    folder, pin = vendored
    new = vendor.update("2.4.0", registry("2.4.0", b"body{margin:1px}", b"body{margin:1px}"), folder, pin)
    assert new.version == "2.4.0"
    assert (folder / "simple.min.css").read_bytes() == b"body{margin:1px}"
    assert vendor.read_pin(pin).sha256 == vendor.digest(b"body{margin:1px}")
    assert vendor.local_errors(folder, pin) == []


def test_update_writes_nothing_when_the_tarball_differs_from_the_tag(vendored):
    folder, pin = vendored
    before = (folder / "simple.min.css").read_bytes(), pin.read_text()
    with pytest.raises(vendor.VendorError):
        vendor.update("2.4.0", registry("2.4.0", b"new", b"tagged"), folder, pin)
    assert ((folder / "simple.min.css").read_bytes(), pin.read_text()) == before


class TestTheMermaidBundle:
    """A bundle the repository builds rather than commits: its file is in a directory of the package, and only the registry holds it."""

    @staticmethod
    def package(body: bytes) -> bytes:
        return package("11.17.2", body, name="package/dist/mermaid.min.js")

    @staticmethod
    def vendored_bundle(tmp_path):
        folder = tmp_path / "vendor"
        folder.mkdir()
        (folder / "mermaid.min.js").write_bytes(BODY)
        pin = folder / "mermaid.pin"
        lines = ["package = mermaid", "version = 11.17.2", "file = dist/mermaid.min.js", f"sha256 = {vendor.digest(BODY)}"]
        pin.write_text("\n".join([*lines, "repository = mermaid-js/mermaid", "source = registry", ""]), encoding="utf-8")
        return folder, pin

    def test_the_committed_bundle_is_the_one_its_pin_names(self):
        assert vendor.local_errors(pin_path=vendor.MERMAID_PIN) == []

    def test_the_bundle_has_its_licence(self):
        assert (vendor.VENDOR / "mermaid.LICENSE").read_text(encoding="utf-8").startswith("The MIT License")

    def test_the_file_is_checked_by_its_name_in_the_vendor_directory(self, tmp_path):
        folder, pin = self.vendored_bundle(tmp_path)
        assert vendor.read_pin(pin).name == "mermaid.min.js"
        assert vendor.local_errors(folder, pin) == []
        (folder / "mermaid.min.js").write_bytes(b"other")
        assert vendor.local_errors(folder, pin)

    def test_only_the_registry_is_compared_and_no_tag_is_fetched(self, tmp_path):
        folder, pin = self.vendored_bundle(tmp_path)
        urls: list[str] = []

        def fetch(url: str) -> bytes:
            urls.append(url)
            return self.package(BODY)

        assert vendor.upstream_errors(fetch, folder, pin) == []
        assert not any(url.startswith(vendor.RAW) for url in urls)

    def test_a_bundle_that_is_not_the_published_one_fails(self, tmp_path):
        folder, pin = self.vendored_bundle(tmp_path)
        assert len(vendor.upstream_errors(lambda url: self.package(b"other"), folder, pin)) == 2

    def test_update_keeps_the_source_and_the_directory_of_the_file(self, tmp_path):
        folder, pin = self.vendored_bundle(tmp_path)
        new = vendor.update("11.18.0", lambda url: self.package(b"new"), folder, pin)
        assert (new.version, new.source) == ("11.18.0", "registry")
        assert (folder / "mermaid.min.js").read_bytes() == b"new"
        assert "source = registry" in pin.read_text(encoding="utf-8")
        assert vendor.local_errors(folder, pin) == []

    def test_a_file_that_leaves_the_package_directory_is_refused(self, tmp_path):
        _, pin = self.vendored_bundle(tmp_path)
        pin.write_text(pin.read_text(encoding="utf-8").replace("dist/mermaid.min.js", "../mermaid.min.js"), encoding="utf-8")
        with pytest.raises(vendor.VendorError):
            vendor.read_pin(pin)

    def test_a_source_other_than_tag_or_registry_is_refused(self, tmp_path):
        _, pin = self.vendored_bundle(tmp_path)
        pin.write_text(pin.read_text(encoding="utf-8").replace("registry", "elsewhere"), encoding="utf-8")
        with pytest.raises(vendor.VendorError):
            vendor.read_pin(pin)

    def test_the_command_checks_every_pin_and_an_update_needs_to_name_one(self, capsys):
        assert vendor.main([]) == 0
        with pytest.raises(SystemExit):
            vendor.main(["--update", "2.4.0"])
