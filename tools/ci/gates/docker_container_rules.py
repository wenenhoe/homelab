#!/usr/bin/env python3
"""Checks that every Ansible `docker_container` task that creates a container keeps the hardening baseline.

The compose gate (compose_hardening_rules) does not read a container that Ansible
starts directly, so this one does. A task sets `cap_drop: [ALL]` and
`security_opts: [no-new-privileges:true]` (container-hardening.md). Anything
that widens the container beyond that is an exception, and an exception needs a
line in EXCEPTIONS with the reason: a `capabilities` entry, `privileged`, a host
`network_mode`, `pid_mode`, `ipc_mode`, `uts` or `userns_mode`, `devices`, a
mount of the Docker socket, or a `security_opts` value other than the one above.
The list also fails on an entry nothing uses any more, so it cannot keep a
reason for something that is gone.

In scope: the playbooks and the tasks and handlers of Ansible roles. A task
whose `state` is `absent` creates nothing and is skipped; Molecule scenarios and
the `molecule_helpers` role are test platforms and are not in scope. A
`command` or `shell` task that runs `docker run` is refused, since it would
start a container this check cannot read.

Task files are read as YAML, so a Jinja value is a quoted string. A parameter
that is only a Jinja expression cannot be judged and is refused: write the
literal list. A tag such as `!vault` is accepted and its value read as text.

Runs in pre-commit (PyYAML only) and so in the pre-commit-checks job.

Usage (from tools/): python -m ci.gates.docker_container_rules
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import yaml
from utils.unique_key_yaml import UniqueKeyLoader

REPO_ROOT = Path(__file__).resolve().parents[3]

SCOPE_GLOBS = (
    "ansible/playbooks/**/*.yaml",
    "ansible/playbooks/**/*.yml",
    "ansible/roles/*/tasks/**/*.yaml",
    "ansible/roles/*/tasks/**/*.yml",
    "ansible/roles/*/handlers/**/*.yaml",
    "ansible/roles/*/handlers/**/*.yml",
)
OUT_OF_SCOPE = ("/molecule/", "ansible/roles/molecule_helpers/")

MODULE_NAMES = ("community.docker.docker_container", "docker_container")
SHELL_MODULES = (
    "ansible.builtin.command",
    "ansible.builtin.shell",
    "ansible.legacy.command",
    "ansible.legacy.shell",
    "command",
    "shell",
)

NO_NEW_PRIVILEGES = ("no-new-privileges:true", "no-new-privileges=true")
# module parameter -> the name the compose gate gives the same setting
HOST_NAMESPACES = {"network_mode": "network_mode", "pid_mode": "pid", "ipc_mode": "ipc", "uts": "uts", "userns_mode": "userns_mode"}
TRUE_WORDS = ("true", "yes", "on", "1")

# file -> task name -> setting -> why the task needs it. The task name is the text in the file, Jinja included.
# A setting is `cap_add:<CAPABILITY>` for each `capabilities` entry, `privileged`, `<key>:host` for a host namespace,
# `devices`, `docker-socket` or `security_opt:<value>`, the names ci.gates.compose_hardening_rules uses. What each
# capability is for: docs/topics/deploy/container-hardening.md.
Exceptions = dict[str, dict[str, dict[str, str]]]
EXCEPTIONS: Exceptions = {
    "ansible/playbooks/bootstrap-security.yaml": {
        "Create the self-signed placeholder": {
            "cap_add:DAC_OVERRIDE": "root writes the new cert and key into a certs volume whose root directory another user may own",
        },
        "Hand the placeholder to the openbao user": {
            "cap_add:CHOWN": "chown -R changes the owner of the placeholder cert and key",
        },
        "Remove the placeholder, and only a self-signed cert": {
            "cap_add:DAC_OVERRIDE": "deleting a file takes write access to the certs directory, which the openbao user owns",
        },
    },
    "ansible/playbooks/volume-file-rm.yaml": {
        "Remove file(s) from the volume ({{ volume_rm_full_name }})": {
            "cap_add:DAC_OVERRIDE": "deleting a file takes write access to the directory holding it, which another user usually owns",
        },
    },
    "ansible/roles/bind9/tasks/main.yaml": {
        "Give the records volume to the bind user": {
            "cap_add:CHOWN": "chown hands the records volume to the bind user",
        },
    },
    "ansible/roles/caddy/tasks/main.yaml": {
        "Validate the staged Caddyfile before it can replace the served one": {
            "cap_add:NET_BIND_SERVICE": "the binary carries a file capability for low ports, so the kernel refuses the exec once every capability is dropped",
        },
    },
    "ansible/roles/compose/tasks/seed_volume.yaml": {
        "Copy staged content into volume ({{ compose_app_item.name ~ '_' ~ compose_volume_item.name }})": {
            "cap_add:CHOWN": "cp -a keeps each file's owner",
            "cap_add:DAC_OVERRIDE": "cp -a writes over files other users own",
            "cap_add:FOWNER": "cp -a keeps each file's mode on files other users own",
            "cap_add:FSETID": "without it a setgid directory is copied without the bit and cp still exits 0",
        },
    },
    "ansible/roles/openbao/tasks/main.yaml": {
        "Chown the data volume to the openbao user": {
            "cap_add:CHOWN": "chown -R changes the owner of the data volume",
            "cap_add:DAC_OVERRIDE": "chown -R has to list directories the previous owner left at 0700",
        },
    },
    "ansible/roles/restore/tasks/main.yaml": {
        "Extract the full archive into a scratch volume once": {
            "cap_add:CHOWN": "tar restores the owner of every entry it extracts",
            "cap_add:DAC_OVERRIDE": "the scratch volume may hold files from an earlier attempt that another user owns",
            "cap_add:FOWNER": "tar restores the mode of every entry it extracts",
            "cap_add:FSETID": "without it a setgid directory is extracted without the bit and tar still exits 0",
        },
        "Check the archive holds a directory for every targeted volume": {
            "cap_add:DAC_READ_SEARCH": "find searches directories other users own; it only reads them",
        },
        "Locate and restore each targeted volume's contents": {
            "cap_add:CHOWN": "cp -a restores each file's owner",
            "cap_add:DAC_OVERRIDE": "the delete before the copy reaches into directories other users own",
            "cap_add:FOWNER": "cp -a restores each file's mode",
            "cap_add:FSETID": "without it a setgid directory is restored without the bit and cp still exits 0",
        },
    },
    "ansible/roles/step_ca_cert/tasks/inspect.yaml": {
        "Read the already-issued cert, if any: {{ step_ca_cert_app_name }}": {
            "cap_add:DAC_OVERRIDE": "the cert is mode 0600 and the app's user owns it; a failed read is taken for no cert and reissues over a valid one",
        },
    },
    "ansible/roles/step_ca_cert/tasks/issue.yaml": {
        "Request the initial cert from step-ca": {
            "cap_add:DAC_OVERRIDE": "writing privkey.pem in a directory the app's user owns, at mode 0600, takes more than root's own access",
        },
        "Hand the issued cert back to its owning user so the app can read it": {
            "cap_add:CHOWN": "chown -R hands the cert directory to the app's user",
        },
    },
}


@dataclass(frozen=True)
class Violation:
    path: str
    task: str
    rule: str
    message: str


class TaskLoader(UniqueKeyLoader):
    """UniqueKeyLoader that also reads a tagged value (`!vault`, `!unsafe`) as the plain value under the tag."""


def _construct_tagged(loader: TaskLoader, _suffix: str, node: yaml.Node) -> object:
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_mapping(node, deep=True)


TaskLoader.add_multi_constructor("!", _construct_tagged)


def _is_jinja(value: object) -> bool:
    return isinstance(value, str) and ("{{" in value or "{%" in value)


def _is_true(value: object) -> bool:
    return value is True or (isinstance(value, str) and value.strip().lower() in TRUE_WORDS)


def _tasks(node: object) -> Iterator[dict[str, object]]:
    """Every mapping at any depth (block, rescue, always, handlers) that holds a module key this check reads."""
    if isinstance(node, dict):
        modules = (*MODULE_NAMES, *SHELL_MODULES)
        if any(key in node for key in modules):
            yield node
        for key, value in node.items():
            # a module's own parameters (docker_container's `command`) are not tasks
            if key not in modules:
                yield from _tasks(value)
    elif isinstance(node, list):
        for value in node:
            yield from _tasks(value)


def _module(task: dict[str, object], names: tuple[str, ...]) -> tuple[str, object] | None:
    for name in names:
        if name in task:
            return name, task[name]
    return None


def _command_text(params: object) -> str:
    """The command a `command` or `shell` task runs, as one string."""
    if isinstance(params, str):
        return params
    if isinstance(params, list):
        return " ".join(str(item) for item in params)
    if isinstance(params, dict):
        parts = [params.get("cmd"), params.get("_raw_params"), params.get("argv")]
        return "\n".join(_command_text(part) for part in parts if part is not None)
    return ""


_COMMENT = re.compile(r"(?:^|(?<=\s))#.*$", re.MULTILINE)
_DOCKER_RUN = re.compile(
    r"(?:^|[;&|(`]|\$\()\s*(?:(?:sudo|exec|command|time)\s+)*(?:\S*/)?docker\s+(?:container\s+)?run\b",
    re.MULTILINE,
)


def _runs_docker(text: str) -> bool:
    """True when `text` runs `docker run` as a command; a comment does not count."""
    return bool(_DOCKER_RUN.search(_COMMENT.sub("", text)))


def _mounts_socket(volumes: object, mounts: object) -> bool:
    for volume in volumes if isinstance(volumes, list) else []:
        if isinstance(volume, str) and "docker.sock" in volume:
            return True
    for mount in mounts if isinstance(mounts, list) else []:
        source = mount.get("source") if isinstance(mount, dict) else None
        if isinstance(source, str) and source.rstrip("/").endswith("docker.sock"):
            return True
    return False


def _list_of_text(value: object) -> list[str] | None:
    """The entries of a literal list of strings, or None when it is anything else."""
    if value is None:
        return []
    if isinstance(value, list) and all(isinstance(item, str) and not _is_jinja(item) for item in value):
        return list(value)
    return None


def _widenings(params: dict[str, object]) -> list[str]:
    """Every setting of the task beyond the baseline, in the form EXCEPTIONS names it."""
    found = [f"cap_add:{item.strip().upper().removeprefix('CAP_')}" for item in params.get("capabilities") or []]
    if _is_true(params.get("privileged")):
        found.append("privileged")
    for key, name in HOST_NAMESPACES.items():
        if str(params.get(key)).strip().lower() == "host":
            found.append(f"{name}:host")
    if params.get("devices"):
        found.append("devices")
    if _mounts_socket(params.get("volumes"), params.get("mounts")):
        found.append("docker-socket")
    found.extend(f"security_opt:{option}" for option in params.get("security_opts") or [] if option not in NO_NEW_PRIVILEGES)
    return found


def _check_task(path: str, name: str, params: dict[str, object], exceptions: Exceptions, used: set[tuple[str, str, str]]) -> list[Violation]:
    found: list[Violation] = []

    def fail(rule: str, message: str) -> None:
        found.append(Violation(path, name, rule, message))

    unjudgeable = False
    for key in ("cap_drop", "capabilities", "security_opts"):
        if _list_of_text(params.get(key)) is None:
            fail("jinja", f"`{key}` must be a literal list of names; this check cannot judge a template or another shape")
            unjudgeable = True
    for key in ("privileged", "devices", "volumes", "mounts", *HOST_NAMESPACES):
        if _is_jinja(params.get(key)):
            fail("jinja", f"`{key}` is only a template; this check cannot judge it, so write the literal value")
            unjudgeable = True
    if unjudgeable:
        return found

    drop = [item.strip().upper() for item in params.get("cap_drop") or []]
    if drop != ["ALL"]:
        fail("cap-drop", "must set `cap_drop: [ALL]`")
    if not any(option in NO_NEW_PRIVILEGES for option in params.get("security_opts") or []):
        fail("no-new-privileges", "must set `security_opts: [no-new-privileges:true]`")
    for setting in _widenings(params):
        if setting in exceptions.get(path, {}).get(name, {}):
            used.add((path, name, setting))
        else:
            fail("exception", f"`{setting}` widens the container beyond the baseline; add it to ci.gates.docker_container_rules.EXCEPTIONS with the reason")
    return found


def check_text(path: str, text: str, exceptions: Exceptions, used: set[tuple[str, str, str]]) -> list[Violation]:
    """Every baseline, exception or `docker run` violation in one task file; the exceptions it relies on are added to `used`."""
    try:
        documents = list(yaml.load_all(text, Loader=TaskLoader))
    except yaml.YAMLError as exc:
        return [Violation(path, "", "unreadable", f"not readable as YAML: {str(exc).splitlines()[0]}")]

    found: list[Violation] = []
    names: set[str] = set()
    for document in documents:
        for task in _tasks(document):
            raw = task.get("name")
            label = raw if isinstance(raw, str) else ""
            shell = _module(task, SHELL_MODULES)
            if shell and _runs_docker(_command_text(shell[1])):
                found.append(
                    Violation(
                        path, label, "docker-run", "runs `docker run`, which starts a container this check cannot read; use community.docker.docker_container"
                    )
                )
            module = _module(task, MODULE_NAMES)
            if module is None:
                continue
            params = module[1]
            if not isinstance(params, dict):
                found.append(Violation(path, label, "module-shape", "the module's parameters must be a mapping, not free-form text"))
                continue
            state = params.get("state")
            if _is_jinja(state):
                found.append(Violation(path, label, "jinja", "`state` is only a template; this check cannot tell whether the task creates a container"))
                continue
            if state == "absent":
                continue
            if not label:
                found.append(Violation(path, label, "task-name", "must have a `name`, which keys its exceptions"))
                continue
            if label in names:
                found.append(
                    Violation(
                        path, label, "duplicate-name", "another docker_container task in this file has the same name, so they would share an exception entry"
                    )
                )
                continue
            names.add(label)
            found.extend(_check_task(path, label, params, exceptions, used))
    return found


def _listed(exceptions: Exceptions) -> set[tuple[str, str, str]]:
    return {(path, task, setting) for path, tasks in exceptions.items() for task, settings in tasks.items() for setting in settings}


def scoped_files(root: Path) -> list[str]:
    """Repo-relative paths of the task files this check covers."""
    found = {path.relative_to(root).as_posix() for pattern in SCOPE_GLOBS for path in root.glob(pattern) if path.is_file()}
    return sorted(path for path in found if not any(part in path for part in OUT_OF_SCOPE))


def check(root: Path, exceptions: Exceptions = EXCEPTIONS) -> list[Violation]:
    """Every violation across the in-scope files, then every exception nothing uses."""
    found: list[Violation] = []
    used: set[tuple[str, str, str]] = set()
    for path in scoped_files(root):
        found.extend(check_text(path, (root / path).read_text(encoding="utf-8"), exceptions, used))
    found.extend(
        Violation(path, task, "stale-exception", f"EXCEPTIONS lists `{setting}` but the task no longer sets it; remove the entry")
        for path, task, setting in sorted(_listed(exceptions) - used)
    )
    return found


def main() -> int:
    violations = check(REPO_ROOT)
    for violation in violations:
        where = f"{violation.path}: {violation.task}" if violation.task else violation.path
        print(f"::error::{where}: {violation.message} [{violation.rule}]", file=sys.stderr)
    if violations:
        print(f"{len(violations)} hardening violation(s) in the docker_container tasks", file=sys.stderr)
        return 1
    print("docker_container tasks: every task keeps the hardening baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
