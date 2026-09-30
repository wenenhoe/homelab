"""backup_plan and backup_hosts: what each host backs up, with every setting resolved.

`backup_plan` takes one host's `resolved_apps` and the shared `backup_defaults`
and returns one entry per backed-up app: its name, its volumes, and every backup
setting (`cron`, `retention_days`, `compression`, `stop_during_backup`,
`cloud_targets`) taken from the app's own `backup:` block when the key is there
and from `backup_defaults` when it is not. A key the app sets wins whatever its
value, and a list is never merged with the default's. An app is backed up
exactly when `backup.volumes` is non-empty, and this is the only place that is
decided. `backup_hosts` returns the hosts, in the order given, whose plan is
non-empty. Both are pure and never modify their inputs. See ADR 0068.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ansible.errors import AnsibleFilterError

BACKUP_SETTINGS = ("cron", "retention_days", "compression", "stop_during_backup", "cloud_targets")


def _is_list(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def backup_plan(resolved_apps: Sequence[Mapping], backup_defaults: Mapping) -> list[dict]:
    """One resolved entry for every app in `resolved_apps` that has backup volumes."""
    if not _is_list(resolved_apps):
        raise AnsibleFilterError(f"backup_plan: resolved_apps must be a list, got {type(resolved_apps).__name__}")
    if not isinstance(backup_defaults, Mapping):
        raise AnsibleFilterError(f"backup_plan: backup_defaults must be a mapping, got {type(backup_defaults).__name__}")
    missing = [key for key in BACKUP_SETTINGS if key not in backup_defaults]
    if missing:
        raise AnsibleFilterError(f"backup_plan: backup_defaults has no {', '.join(missing)}")

    plan = []
    for app in resolved_apps:
        if not isinstance(app, Mapping) or "name" not in app:
            raise AnsibleFilterError(f"backup_plan: every resolved_apps entry needs a 'name', got: {app}")
        block = app.get("backup")
        if block is None:
            continue
        if not isinstance(block, Mapping):
            raise AnsibleFilterError(f"backup_plan: '{app['name']}' has a backup block that is not a mapping, got {type(block).__name__}")
        volumes = block.get("volumes")
        if volumes is None:
            continue
        if not _is_list(volumes):
            raise AnsibleFilterError(f"backup_plan: '{app['name']}' backup.volumes must be a list, got {type(volumes).__name__}")
        if not volumes:
            continue

        entry = {"name": app["name"], "volumes": list(volumes)}
        for key in BACKUP_SETTINGS:
            entry[key] = block[key] if key in block else backup_defaults[key]
        if not _is_list(entry["cloud_targets"]):
            raise AnsibleFilterError(f"backup_plan: '{app['name']}' cloud_targets must be a list, got {type(entry['cloud_targets']).__name__}")
        entry["cloud_targets"] = list(entry["cloud_targets"])
        plan.append(entry)
    return plan


def backup_hosts(hosts: Sequence[str], hostvars: Mapping) -> list[str]:
    """The hosts, in the order given, whose `backup_plan` is non-empty."""
    if not _is_list(hosts):
        raise AnsibleFilterError(f"backup_hosts: hosts must be a list, got {type(hosts).__name__}")
    if not isinstance(hostvars, Mapping):
        raise AnsibleFilterError(f"backup_hosts: hostvars must be a mapping, got {type(hostvars).__name__}")

    backing_up = []
    for host in hosts:
        if host not in hostvars:
            raise AnsibleFilterError(f"backup_hosts: '{host}' is not in hostvars")
        try:
            plan = hostvars[host]["backup_plan"]
        except KeyError:
            raise AnsibleFilterError(f"backup_hosts: '{host}' has no backup_plan") from None
        if plan:
            backing_up.append(host)
    return backing_up


class FilterModule:
    def filters(self):
        return {"backup_plan": backup_plan, "backup_hosts": backup_hosts}
