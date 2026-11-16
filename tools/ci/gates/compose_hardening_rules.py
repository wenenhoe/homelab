#!/usr/bin/env python3
"""Checks that every service in a production compose file keeps the hardening baseline.

Each service sets `cap_drop: [ALL]` and `security_opt: [no-new-privileges:true]`
(container-hardening.md). Anything that widens a container beyond that is an
exception, and an exception needs a line in EXCEPTIONS with the reason: a
`cap_add` capability, `privileged`, a host `network_mode`, `pid`, `ipc`, `uts`
or `userns_mode`, `devices`, a mount of the Docker socket, or a `security_opt`
value other than the one above. The list also fails on an entry nothing uses
any more, so it cannot keep a reason for something that is gone.

In scope: the compose files under docker/ and the compose templates of Ansible
roles. Jinja is read as text: `{{ ... }}` becomes a placeholder and a line that
holds only a `{% ... %}` statement is dropped, so the body of an `if` or `for`
is read once. A statement inside a line is refused, since it cannot be
dropped without changing the YAML. Molecule fixtures are test platforms and are
not in scope.

Runs in pre-commit (PyYAML only) and so in the pre-commit-checks job.

Usage (from tools/): python -m ci.gates.compose_hardening_rules
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml
from utils.unique_key_yaml import UniqueKeyLoader

REPO_ROOT = Path(__file__).resolve().parents[3]

SCOPE_GLOBS = (
    "docker/**/compose*.yaml",
    "docker/**/compose*.yml",
    "docker/**/compose*.yaml.j2",
    "docker/**/compose*.yml.j2",
    "ansible/roles/*/templates/**/compose*.j2",
)

NO_NEW_PRIVILEGES = ("no-new-privileges:true", "no-new-privileges=true")
HOST_NAMESPACES = ("network_mode", "pid", "ipc", "uts", "userns_mode")

# file -> service -> setting -> why the service needs it. A setting is `cap_add:<CAPABILITY>`, `privileged`,
# `<key>:host` for a host namespace, `devices`, `docker-socket` or `security_opt:<value>`. What each
# capability is for: docs/topics/deploy/container-hardening.md.
Exceptions = dict[str, dict[str, dict[str, str]]]
EXCEPTIONS: Exceptions = {
    "docker/beszel-agent/compose.yaml": {
        "beszel-agent": {
            "network_mode:host": "reads host-level network interface statistics, which the host network gives it",
        },
        "dockerproxy": {
            "docker-socket": "the socket proxy: the Docker API it filters comes from the socket, mounted read-only",
        },
    },
    "ansible/roles/backup_agent/templates/compose.yaml.j2": {
        "backup-dockerproxy": {
            "docker-socket": "the socket proxy the backup agent stops containers through: the socket is mounted read-only",
        },
        "backup-agent": {
            "cap_add:DAC_READ_SEARCH": "root over files other users own (schedule files, each volume's owner): it only reads them",
        },
    },
    "docker/caddy/compose.yaml": {
        "caddy": {
            "cap_add:NET_BIND_SERVICE": "the base image sets cap_net_bind_service on the binary and the process runs as root",
        },
    },
    "docker/step-ca/compose.yaml.j2": {
        "step-ca": {
            "cap_add:NET_BIND_SERVICE": "the binary carries the capability with the effective bit set, so the kernel refuses the exec without it",
        },
    },
    "docker/openbao/compose.yaml.j2": {
        "openbao": {
            "cap_add:IPC_LOCK": "mlock, so secrets never get swapped to disk",
        },
    },
    "docker/tinyauth/compose.yaml": {
        "tinyauth": {
            "cap_add:DAC_OVERRIDE": "root over a /data the volume seed leaves owned by another user; SQLite must create its journal beside the database",
        },
    },
    "docker/minecraft/compose.yaml.j2": {
        "bluemap": {
            "cap_add:DAC_OVERRIDE": "creates files in a directory another user owns",
        },
        "mc": {
            "cap_add:CHOWN": "the entrypoint starts as root to chown a volume",
            "cap_add:SETGID": "the entrypoint drops to another user after the chown",
            "cap_add:SETUID": "the entrypoint drops to another user after the chown",
        },
        "backups": {
            "cap_add:CHOWN": "the entrypoint starts as root to chown a volume",
            "cap_add:SETGID": "the entrypoint drops to another user after the chown",
            "cap_add:SETUID": "the entrypoint drops to another user after the chown",
        },
    },
    "docker/lldap/compose.yaml.j2": {
        "lldap": {
            "cap_add:CHOWN": "the entrypoint chowns /data before it drops to another user",
            "cap_add:DAC_OVERRIDE": "the entrypoint writes to /data as a check",
            "cap_add:SETGID": "the entrypoint drops to another user",
            "cap_add:SETUID": "the entrypoint drops to another user",
        },
    },
    "docker/seaweedfs/compose.yaml.j2": {
        "seaweedfs": {
            "cap_add:CHOWN": "the entrypoint starts as root to chown a volume",
            "cap_add:SETGID": "the entrypoint drops to another user after the chown",
            "cap_add:SETUID": "the entrypoint drops to another user after the chown",
        },
    },
    "docker/minecraft/compose.restore.yaml": {
        "restore-backup": {
            "cap_add:CHOWN": "tar restores the owner of every file it writes",
            "cap_add:DAC_OVERRIDE": "run_restore.sh deletes everything in /data, which uid 1000 owns",
            "cap_add:FOWNER": "tar restores the mode of every file it writes",
        },
    },
    "docker/librespeed/compose.yaml": {
        "librespeed": {
            "cap_add:CHOWN": "the entrypoint chowns the web root to www-data before it drops to that user",
            "cap_add:DAC_OVERRIDE": "removes the web root's subdirectories on every start; they belong to www-data",
            "cap_add:FOWNER": "removes the web root's top level, which is www-data's in a sticky directory",
            "cap_add:SETGID": "the entrypoint drops to www-data",
            "cap_add:SETUID": "the entrypoint drops to www-data",
        },
    },
}

_EXPRESSION = re.compile(r"\{\{.*?\}\}", re.DOTALL)
_COMMENT = re.compile(r"\{#.*?#\}", re.DOTALL)
_STATEMENT_LINE = re.compile(r"^\s*\{%.*%\}\s*$")


@dataclass(frozen=True)
class Violation:
    path: str
    service: str
    rule: str
    message: str


def _read(text: str) -> tuple[object, str | None]:
    """The document Jinja leaves as plain YAML, or the reason it cannot be read."""
    text = _COMMENT.sub("", _EXPRESSION.sub("JINJA", text))
    lines = []
    for line in text.splitlines():
        if _STATEMENT_LINE.match(line):
            continue
        if "{%" in line:
            return None, "a {% %} statement shares a line with other text; put each statement on its own line"
        lines.append(line)
    try:
        return yaml.load("\n".join(lines), Loader=UniqueKeyLoader), None  # noqa: S506 - UniqueKeyLoader is a SafeLoader
    except yaml.YAMLError as exc:
        return None, f"not readable as YAML once Jinja is removed: {str(exc).splitlines()[0]}"


def _is_true(value: object) -> bool:
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


def _mounts_socket(volume: object) -> bool:
    """A volume entry, in short (`src:dst:mode`) or long (`source:`) form, whose source is a Docker socket."""
    if isinstance(volume, dict):
        source = volume.get("source")
    elif isinstance(volume, str):
        source = volume.split(":", 1)[0]
    else:
        return False
    return isinstance(source, str) and source.rstrip("/").endswith("docker.sock")


def _widenings(service: dict[str, object]) -> list[str]:
    """Every setting of `service` that goes beyond the baseline, in the form EXCEPTIONS names it."""
    found: list[str] = []
    for capability in service.get("cap_add") or []:
        found.append(f"cap_add:{str(capability).upper().removeprefix('CAP_')}")
    if _is_true(service.get("privileged")):
        found.append("privileged")
    for key in HOST_NAMESPACES:
        if str(service.get(key)).strip().lower() == "host":
            found.append(f"{key}:host")
    if service.get("devices"):
        found.append("devices")
    if any(_mounts_socket(volume) for volume in service.get("volumes") or []):
        found.append("docker-socket")
    found.extend(f"security_opt:{option}" for option in service.get("security_opt") or [] if option not in NO_NEW_PRIVILEGES)
    return found


def check_text(path: str, text: str, exceptions: Exceptions, used: set[tuple[str, str, str]]) -> list[Violation]:
    """Every baseline or exception violation in one compose file; the exceptions it relies on are added to `used`."""
    document, problem = _read(text)
    if problem:
        return [Violation(path, "", "unreadable", problem)]
    services = document.get("services") if isinstance(document, dict) else None
    if not isinstance(services, dict) or not services:
        return [Violation(path, "", "no-services", "has no `services` mapping to check")]
    if "include" in document:
        return [Violation(path, "", "include", "`include` pulls in services this check cannot read; put them in this file")]

    found: list[Violation] = []
    for name, service in services.items():
        if not isinstance(service, dict):
            found.append(Violation(path, name, "service-shape", "a service must be a mapping"))
            continue

        def fail(rule: str, message: str, name: str = name) -> None:
            found.append(Violation(path, name, rule, message))

        if "extends" in service:
            fail("extends", "`extends` takes settings from another file this check cannot read; write them in this service")
        drop = service.get("cap_drop") or []
        if "ALL" not in [str(item).upper() for item in drop]:
            fail("cap-drop", "must set `cap_drop: [ALL]`")
        options = service.get("security_opt") or []
        if not any(option in NO_NEW_PRIVILEGES for option in options):
            fail("no-new-privileges", "must set `security_opt: [no-new-privileges:true]`")
        for setting in _widenings(service):
            if setting in exceptions.get(path, {}).get(name, {}):
                used.add((path, name, setting))
            else:
                fail(
                    "exception", f"`{setting}` widens the container beyond the baseline; add it to ci.gates.compose_hardening_rules.EXCEPTIONS with the reason"
                )
    return found


def _listed(exceptions: Exceptions) -> set[tuple[str, str, str]]:
    return {(path, service, setting) for path, services in exceptions.items() for service, settings in services.items() for setting in settings}


def scoped_files(root: Path) -> list[str]:
    """Repo-relative paths of the compose files this check covers."""
    found = {path.relative_to(root).as_posix() for pattern in SCOPE_GLOBS for path in root.glob(pattern) if path.is_file()}
    return sorted(path for path in found if "/molecule/" not in path)


def check(root: Path, exceptions: Exceptions = EXCEPTIONS) -> list[Violation]:
    """Every violation across the in-scope files, then every exception nothing uses."""
    found: list[Violation] = []
    used: set[tuple[str, str, str]] = set()
    for path in scoped_files(root):
        found.extend(check_text(path, (root / path).read_text(encoding="utf-8"), exceptions, used))
    found.extend(
        Violation(path, service, "stale-exception", f"EXCEPTIONS lists `{setting}` but the service no longer sets it; remove the entry")
        for path, service, setting in sorted(_listed(exceptions) - used)
    )
    return found


def main() -> int:
    violations = check(REPO_ROOT)
    for violation in violations:
        where = f"{violation.path}: {violation.service}" if violation.service else violation.path
        print(f"::error::{where}: {violation.message} [{violation.rule}]", file=sys.stderr)
    if violations:
        print(f"{len(violations)} hardening violation(s) in the compose files", file=sys.stderr)
        return 1
    print("compose files: every service keeps the hardening baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
