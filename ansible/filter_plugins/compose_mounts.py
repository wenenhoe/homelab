"""compose_mounts: find what a stack's services mount from the stack directory, and label them with it.

Compose does not recreate a service whose bind-mounted file changed, and a
container keeps the old content of a file that was replaced by a rename
(ADR 0087). roles/compose/tasks/deploy.yaml therefore writes a
`compose.override.yaml` next to `compose.yaml` that gives each affected service
a label holding a checksum of the files it mounts; a changed label recreates
that service and no other. Two filters make that:

    compose_mounts(compose_yaml, stack_dir)
        -> {service: [path relative to stack_dir, ...]}

        The deployed compose file's bind mounts that are read-only, in short
        (`./a:/b:ro`) and long (`type: bind`, `read_only: true`) syntax, and
        whose source is inside `stack_dir`. Named volumes, writable binds, the
        Docker socket and any other host path are not counted, nor is
        `stack_dir` itself: the override lives there. A read-only source that
        holds an unresolved `$` is an error, since it cannot be told from a path
        outside; a `$` in the target or the options does not matter, and a
        colon inside `${...}` does not split the mount.

    compose_mounts_override(mounts, stat_results, find_results) -> str

        The text of `compose.override.yaml`, empty for no mounts. The two result
        lists are the registered loops of `stat` over each path in `mounts`
        (checksum on) and of `find` (recursive, hidden files, checksum on) over
        each of those that is a directory, whose loop item is the stat result.
        A missing path counts as its own state, so one that appears recreates.
"""

from __future__ import annotations

import hashlib
import posixpath

import yaml
from ansible.errors import AnsibleFilterError

LABEL = "homelab.mounted-files-sha256"


def _fields(mount: str) -> list[str]:
    """Split a short-syntax mount at its colons, leaving those inside a `${...}` default (`${A:-./a}`) alone."""
    fields, current, depth, index = [], "", 0, 0
    while index < len(mount):
        if mount.startswith("${", index):
            depth, current, index = depth + 1, current + "${", index + 2
            continue
        char = mount[index]
        if char == "}" and depth:
            depth -= 1
        if char == ":" and not depth:
            fields.append(current)
            current = ""
        else:
            current += char
        index += 1
    return [*fields, current]


def _bind_source(mount: object) -> tuple[str, bool] | None:
    """Return a bind mount's `(source, read_only)`, or None for any other mount."""
    if isinstance(mount, str):
        parts = _fields(mount)
        if len(parts) < 2 or not parts[0].startswith(("/", ".", "~", "$")):
            return None
        return parts[0], "ro" in (parts[2].split(",") if len(parts) > 2 else [])
    if isinstance(mount, dict) and mount.get("type") == "bind" and isinstance(mount.get("source"), str):
        return mount["source"], mount.get("read_only") is True
    return None


def compose_mounts(compose_yaml: str, stack_dir: str) -> dict[str, list[str]]:
    """Map each service to the read-only mounts it takes from inside `stack_dir`."""
    if not isinstance(compose_yaml, str):
        raise AnsibleFilterError(f"compose_mounts: expected the compose file's text, got {type(compose_yaml).__name__}")
    try:
        document = yaml.safe_load(compose_yaml)
    except yaml.YAMLError as exc:
        raise AnsibleFilterError(f"compose_mounts: the compose file does not parse: {exc}") from exc
    services = (document or {}).get("services") if isinstance(document, dict) else None
    if services is None:
        return {}
    if not isinstance(services, dict):
        raise AnsibleFilterError(f"compose_mounts: 'services' must be a mapping, got {type(services).__name__}")
    root = posixpath.normpath(stack_dir)
    result: dict[str, list[str]] = {}
    for name, service in services.items():
        mounts = service.get("volumes") if isinstance(service, dict) else None
        paths: set[str] = set()
        for mount in mounts if isinstance(mounts, list) else []:
            bind = _bind_source(mount)
            if bind is None or not bind[1]:
                continue
            source = bind[0]
            if "$" in source:
                raise AnsibleFilterError(f"compose_mounts: the mount source '{source}' of service '{name}' holds a variable, which cannot be placed")
            if source.startswith("~"):
                continue
            relative = posixpath.relpath(posixpath.normpath(posixpath.join(root, source)), root)
            if relative != "." and relative != ".." and not relative.startswith("../"):
                paths.add(relative)
        if paths:
            result[str(name)] = sorted(paths)
    return result


def _digests(stat_results: list[dict], find_results: list[dict]) -> dict[str, list[str]]:
    """Return, per mounted path, the lines that say what is on the host there."""
    found = {result["item"]["item"]: result["files"] for result in find_results}
    digests: dict[str, list[str]] = {}
    for result in stat_results:
        path, stat = result["item"], result["stat"]
        if not stat.get("exists"):
            digests[path] = [f"{path}\0absent"]
        elif stat.get("isdir"):
            root = stat["path"].rstrip("/") + "/"
            digests[path] = [f"{path}\0dir"] + [f"{path}\0{file['path'].removeprefix(root)}\0{file['checksum']}" for file in found.get(path, [])]
        else:
            digests[path] = [f"{path}\0{stat.get('checksum')}"]
    return digests


def compose_mounts_override(mounts: dict[str, list[str]], stat_results: list[dict], find_results: list[dict]) -> str:
    """Return the text of the override file that labels each service with the checksum of its mounts."""
    if not isinstance(mounts, dict):
        raise AnsibleFilterError(f"compose_mounts_override: expected the mounts mapping, got {type(mounts).__name__}")
    if not mounts:
        return ""
    digests = _digests(stat_results, find_results)
    services = {}
    for name, paths in sorted(mounts.items()):
        missing = [path for path in paths if path not in digests]
        if missing:
            raise AnsibleFilterError(f"compose_mounts_override: no stat result for {missing} of service '{name}'")
        lines = sorted(line for path in paths for line in digests[path])
        services[name] = {"labels": {LABEL: hashlib.sha256("\n".join(lines).encode()).hexdigest()}}
    return yaml.safe_dump({"services": services}, sort_keys=True)


class FilterModule:
    def filters(self):
        return {"compose_mounts": compose_mounts, "compose_mounts_override": compose_mounts_override}
