"""The hooks a machine without a need skips, and the probes that decide it."""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, create_autospec

import pytest
import yaml
from deliver_series import probes
from deliver_series.needs import NEEDS, skipped

CONFIG = Path(__file__).resolve().parents[3] / ".config" / ".pre-commit-config.yaml"
DOCKER, GO, GITHUB, ANSIBLE = (need.name for need in NEEDS)


def all_met() -> dict:
    return {need.name: (lambda: None) for need in NEEDS}


def test_a_machine_with_every_need_skips_nothing() -> None:
    assert skipped(all_met()) == {}


def test_a_missing_need_skips_its_hooks_and_no_others() -> None:
    found = skipped({**all_met(), DOCKER: lambda: "no daemon"})

    assert found == dict.fromkeys(("dclint-docker", "hadolint-docker", "actionlint-docker"), "a Docker daemon: no daemon")


def test_every_need_that_is_missing_is_named() -> None:
    found = skipped({**all_met(), GO: lambda: "offline", GITHUB: lambda: "answered 403", ANSIBLE: lambda: "not installed: x.y"})

    assert found == {
        "gitleaks": "a download of the Go toolchain: offline",
        "zizmor": "the GitHub API: answered 403",
        "ansible-lint": "the Ansible collections: not installed: x.y",
    }


def configured_hooks() -> list[str]:
    return [hook["id"] for repo in yaml.safe_load(CONFIG.read_text())["repos"] for hook in repo["hooks"]]


def test_every_hook_a_need_names_is_in_the_pre_commit_configuration() -> None:
    named = {hook for need in NEEDS for hook in need.hooks}

    assert named <= set(configured_hooks())


def test_every_docker_hook_of_the_pre_commit_configuration_is_listed() -> None:
    named = {hook for need in NEEDS for hook in need.hooks}

    assert {hook for hook in configured_hooks() if hook.endswith("-docker")} <= named


@pytest.fixture
def bin_dir(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The only directory on PATH, so a program is found only when a test puts it there."""
    directory = tmp_path_factory.mktemp("bin")
    monkeypatch.setenv("PATH", str(directory))
    return directory


def program(directory: Path, name: str, body: str) -> None:
    script = directory / name
    script.write_text(f"#!/bin/bash\n{body}\n")
    script.chmod(0o755)


def test_docker_is_met_when_the_daemon_answers(bin_dir: Path) -> None:
    program(bin_dir, "docker", "echo 27.0")

    assert probes.docker() is None


def test_docker_is_missing_when_the_daemon_does_not_answer(bin_dir: Path) -> None:
    program(bin_dir, "docker", "echo 'Cannot connect to the Docker daemon' >&2; exit 1")

    assert probes.docker() == "`docker info` failed: Cannot connect to the Docker daemon"


def test_docker_is_missing_when_it_is_not_installed(bin_dir: Path) -> None:
    assert "`docker` is not installed" in str(probes.docker())


def reply(status: int) -> MagicMock:
    """What `urlopen` gives back: a context manager around a response."""
    response = MagicMock(status=status)
    response.__enter__.return_value = response
    return response


def test_a_url_that_answers_200_is_met(monkeypatch: pytest.MonkeyPatch) -> None:
    opened = create_autospec(probes.urllib.request.urlopen, return_value=reply(200))
    monkeypatch.setattr(probes.urllib.request, "urlopen", opened)

    assert probes.answers("https://example.invalid/x") is None
    opened.assert_called_once_with("https://example.invalid/x", timeout=probes.PROBE_SECONDS)


@pytest.mark.parametrize("code", [401, 403, 500])
def test_a_url_that_refuses_is_missing_with_its_status(monkeypatch: pytest.MonkeyPatch, code: int) -> None:
    refusal = urllib.error.HTTPError("https://example.invalid/x", code, "no", {}, None)  # type: ignore[arg-type]
    monkeypatch.setattr(probes.urllib.request, "urlopen", create_autospec(probes.urllib.request.urlopen, side_effect=refusal))

    assert probes.answers("https://example.invalid/x") == f"https://example.invalid/x answered {code}"


def test_a_url_that_cannot_be_reached_is_missing_with_the_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    failure = urllib.error.URLError("Tunnel connection failed: 403 Forbidden")
    monkeypatch.setattr(probes.urllib.request, "urlopen", create_autospec(probes.urllib.request.urlopen, side_effect=failure))

    assert probes.answers("https://example.invalid/x") == "https://example.invalid/x cannot be reached: <urlopen error Tunnel connection failed: 403 Forbidden>"


def test_a_url_that_is_not_https_is_refused() -> None:
    with pytest.raises(ValueError, match="not an https URL"):
        probes.answers("file:///etc/passwd")


REQUIREMENTS = """
collections:
  - name: community.docker
    version: "5.4.1"
  - name: ansible.posix
    version: "2.2.2"
  - name: https://github.com/O-X-L/ansible-opnsense.git
    type: git
    version: abc
"""


def listing(*names: str) -> str:
    return json.dumps({"/home/user/.ansible/collections/ansible_collections": {name: {"version": "1"} for name in names}})


def test_a_collection_pinned_by_url_has_no_name_to_require() -> None:
    assert probes.required_collections(REQUIREMENTS) == ["community.docker", "ansible.posix"]


def test_collections_are_read_from_every_path_of_the_listing() -> None:
    both = json.dumps({"/a": {"community.docker": {}}, "/b": {"ansible.posix": {}}})

    assert probes.installed_collections(both) == {"community.docker", "ansible.posix"}


@pytest.fixture
def ansible_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("ansible")
    (directory / "requirements.yml").write_text(REQUIREMENTS)
    return directory


def test_collections_are_met_when_every_named_one_is_installed(bin_dir: Path, ansible_dir: Path) -> None:
    program(bin_dir, "uv", f"echo '{listing('community.docker', 'ansible.posix', 'other.thing')}'")

    assert probes.ansible_collections(ansible_dir) is None


def test_the_collections_not_installed_are_named(bin_dir: Path, ansible_dir: Path) -> None:
    program(bin_dir, "uv", f"echo '{listing('community.docker')}'")

    assert probes.ansible_collections(ansible_dir) == "not installed: ansible.posix"


def test_collections_are_missing_when_the_listing_fails(bin_dir: Path, ansible_dir: Path) -> None:
    program(bin_dir, "uv", "echo 'no such command' >&2; exit 2")

    assert probes.ansible_collections(ansible_dir) == "`ansible-galaxy collection list` failed: no such command"


def test_collections_are_missing_when_the_listing_is_not_json(bin_dir: Path, ansible_dir: Path) -> None:
    program(bin_dir, "uv", "echo 'not json'")

    assert "the list of collections cannot be read" in str(probes.ansible_collections(ansible_dir))


def test_collections_are_missing_when_uv_is_not_installed(bin_dir: Path, ansible_dir: Path) -> None:
    assert "`uv` is not installed" in str(probes.ansible_collections(ansible_dir))


def test_the_real_probes_answer_every_need(tmp_path: Path) -> None:
    assert set(probes.real(tmp_path)) == {need.name for need in NEEDS}
