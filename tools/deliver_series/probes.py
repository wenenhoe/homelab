"""The probes of `needs.py`, each asking the machine the question the hook would."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

import yaml
from land_series.run import CommandError, run

from deliver_series.needs import Probe
from deliver_series.repository import HOMELAB

PROBE_SECONDS = 20
# What `gitleaks` is built with: a Go toolchain newer than the one installed is downloaded from here.
GO_TOOLCHAIN_URL = "https://proxy.golang.org/golang.org/toolchain/@v/list"
# What `zizmor`'s ref-confusion audit lists: the branches of another repository. It can answer 401 or 403 where the API itself is reachable.
GITHUB_URL = "https://api.github.com/repos/actions/checkout/branches?per_page=1"


def docker() -> str | None:
    try:
        done = run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=PROBE_SECONDS)
    except CommandError as error:
        return str(error)
    return None if done.returncode == 0 else f"`docker info` failed: {done.output.splitlines()[-1] if done.output else 'no output'}"


def answers(url: str) -> str | None:
    """None when a GET of `url` is answered with success, else what came back."""
    if not url.startswith("https://"):
        raise ValueError(f"{url} is not an https URL")
    try:
        with urllib.request.urlopen(url, timeout=PROBE_SECONDS) as response:  # noqa: S310 -- the scheme is checked above
            return None if response.status == 200 else f"{url} answered {response.status}"
    except urllib.error.HTTPError as error:
        return f"{url} answered {error.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return f"{url} cannot be reached: {error}"


def go_toolchain() -> str | None:
    return answers(GO_TOOLCHAIN_URL)


def github_api() -> str | None:
    return answers(GITHUB_URL)


def required_collections(requirements: str) -> list[str]:
    """The collections `requirements.yml` names. One pinned by a git URL has no name to read, so it is not among them."""
    entries = yaml.safe_load(requirements).get("collections", [])
    return [entry["name"] for entry in entries if "://" not in entry["name"]]


def installed_collections(listing: str) -> set[str]:
    """The collections in the JSON of `ansible-galaxy collection list --format json`."""
    return {name for found in json.loads(listing).values() for name in found}


def ansible_collections(ansible_dir: Path) -> str | None:
    try:
        wanted = required_collections((ansible_dir / "requirements.yml").read_text())
        done = run(["uv", "run", "ansible-galaxy", "collection", "list", "--format", "json"], cwd=ansible_dir, timeout=300)
    except (CommandError, OSError) as error:
        return str(error)
    if done.returncode != 0:
        return f"`ansible-galaxy collection list` failed: {done.output.splitlines()[-1] if done.output else 'no output'}"
    try:
        missing = sorted(set(wanted) - installed_collections(done.text))
    except (ValueError, AttributeError) as error:
        return f"the list of collections cannot be read: {error}"
    return f"not installed: {', '.join(missing)}" if missing else None


def real(ansible_dir: Path) -> dict[str, Probe]:
    """The probes by the name of the need they answer."""
    by_name = {"a Docker daemon": docker, "a download of the Go toolchain": go_toolchain, "the GitHub API": github_api}
    by_name["the Ansible collections"] = lambda: ansible_collections(ansible_dir)
    if set(by_name) != {need.name for need in HOMELAB.needs}:
        raise RuntimeError("every need in needs.py has exactly one probe")
    return by_name
