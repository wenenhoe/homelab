"""The runc wrapper adds the environment's certificate authorities to a container, and writes nothing outside it."""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from cloud_session import runc_ca


def pem(body: str) -> str:
    return f"-----BEGIN CERTIFICATE-----\n{body}\n-----END CERTIFICATE-----"


STANDARD, ADDED = pem("c3RhbmRhcmQ="), pem("YWRkZWQ=")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    root = tmp_path / "rootfs"
    (root / "etc/ssl/certs").mkdir(parents=True)
    (root / "etc/ssl/certs/ca-certificates.crt").write_text(STANDARD + "\n")
    return root


def store(root: Path) -> list[str]:
    return runc_ca.certificates(root / "etc/ssl/certs/ca-certificates.crt")


def test_only_the_certificates_mozilla_lacks_are_added(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle.crt"
    bundle.write_text(f"{STANDARD}\n{ADDED}\n{ADDED}\n")
    (tmp_path / "mozilla").mkdir()
    (tmp_path / "mozilla/one.crt").write_text(STANDARD)

    assert runc_ca.added(bundle, str(tmp_path / "mozilla/*.crt")) == [ADDED]


def test_with_nothing_to_compare_against_no_container_is_changed(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="no Mozilla certificates"):
        runc_ca.added(tmp_path / "bundle.crt", str(tmp_path / "mozilla/*.crt"))


def test_a_container_gets_the_certificate_in_its_store_and_as_a_local_one(root: Path) -> None:
    runc_ca.trust(root, [ADDED])
    runc_ca.trust(root, [ADDED])

    assert store(root) == [STANDARD, ADDED]
    assert (root / "usr/local/share/ca-certificates/session-egress-0.crt").read_text() == ADDED + "\n"


@pytest.mark.parametrize(
    "linked",
    [
        pytest.param("etc/ssl/certs/ca-certificates.crt", id="the store"),
        pytest.param("usr/local/share/ca-certificates", id="the local directory"),
        pytest.param("usr/local/share/ca-certificates/session-egress-0.crt", id="a local certificate"),
    ],
)
def test_a_link_in_the_image_sends_no_write_outside_it(root: Path, tmp_path: Path, linked: str) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "file").write_text(STANDARD)
    path = root / linked
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    path.symlink_to(outside if linked.endswith("ca-certificates") else outside / "file")

    runc_ca.trust(root, [ADDED])

    assert [p.name for p in outside.iterdir()] == ["file"]
    assert (outside / "file").read_text() == STANDARD


@pytest.mark.parametrize(
    ("args", "creates"),
    [
        pytest.param(["--root", "/r", "create", "--bundle", "BUNDLE", "id"], True, id="create"),
        pytest.param(["--root", "/r", "start", "id"], False, id="start"),
    ],
)
def test_runc_is_handed_the_arguments_after_a_create_changes_its_container(root: Path, tmp_path: Path, args: list[str], creates: bool) -> None:
    (tmp_path / "config.json").write_text(json.dumps({"root": {"path": "rootfs"}}))
    args = [str(tmp_path) if arg == "BUNDLE" else arg for arg in args]
    with patch.object(os, "execv", autospec=True) as execv, patch.object(runc_ca, "added", autospec=True, return_value=[ADDED]):
        runc_ca.main(args)

    execv.assert_called_once_with(runc_ca.RUNC, ["runc", *args])
    assert (ADDED in store(root)) is creates


def test_the_wrapper_runs_by_itself_on_the_machines_python() -> None:
    source = Path(runc_ca.__file__).read_text()
    tree = ast.parse(source, feature_version=(3, 12))
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}

    assert source.startswith("#!/usr/bin/python3 -I\n")
    assert not [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert imported <= sys.stdlib_module_names
