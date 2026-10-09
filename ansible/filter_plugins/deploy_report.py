"""deploy_report: every host's deploy results, grouped by outcome, for the end-of-run report.

Takes the hosts to report on and `hostvars`, and returns `{host: {outcome: [app, ...]}}`.
A host's `compose_app_results` is a list of `{name, status}` entries the compose
role appends as each app finishes, `status` being `ok`, `changed` or `failed`;
when an app is recorded twice the last status wins. An app in the host's
`resolved_apps` with no entry is `unfinished`: the host stopped before it
finished. Outcomes come in the order `failed`, `unfinished`, `changed`, `ok`,
and one with no apps is left out. A host with nothing recorded and nothing
resolved is left out, and the result is empty when no host recorded anything,
so a run that deployed nothing reports nothing. Pure; never modifies its inputs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ansible.errors import AnsibleFilterError

OUTCOMES = ("failed", "unfinished", "changed", "ok")
RECORDED_STATUSES = frozenset({"ok", "changed", "failed"})


def _is_list(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def _recorded(host: str, host_vars: Mapping) -> dict[str, str]:
    """The status of every app the host recorded, keyed by name in first-recorded order."""
    try:
        results = host_vars["compose_app_results"]
    except KeyError:
        return {}
    if not _is_list(results):
        raise AnsibleFilterError(f"deploy_report: '{host}' compose_app_results must be a list, got {type(results).__name__}")

    statuses: dict[str, str] = {}
    for entry in results:
        if not isinstance(entry, Mapping) or "name" not in entry or "status" not in entry:
            raise AnsibleFilterError(f"deploy_report: every compose_app_results entry of '{host}' needs a 'name' and a 'status', got: {entry}")
        if entry["status"] not in RECORDED_STATUSES:
            expected = sorted(RECORDED_STATUSES)
            raise AnsibleFilterError(f"deploy_report: '{host}' recorded '{entry['name']}' with status '{entry['status']}', expected one of {expected}")
        statuses[entry["name"]] = entry["status"]
    return statuses


def _resolved(host: str, host_vars: Mapping) -> list[str]:
    try:
        apps = host_vars["resolved_apps"]
    except KeyError:
        raise AnsibleFilterError(f"deploy_report: '{host}' has no resolved_apps") from None
    if not _is_list(apps):
        raise AnsibleFilterError(f"deploy_report: '{host}' resolved_apps must be a list, got {type(apps).__name__}")
    for app in apps:
        if not isinstance(app, Mapping) or "name" not in app:
            raise AnsibleFilterError(f"deploy_report: every resolved_apps entry of '{host}' needs a 'name', got: {app}")
    return [app["name"] for app in apps]


def deploy_report(hosts: Sequence[str], hostvars: Mapping) -> dict[str, dict[str, list[str]]]:
    """Each host's apps grouped by outcome; empty when no host recorded a result."""
    if not _is_list(hosts):
        raise AnsibleFilterError(f"deploy_report: hosts must be a list, got {type(hosts).__name__}")
    if not isinstance(hostvars, Mapping):
        raise AnsibleFilterError(f"deploy_report: hostvars must be a mapping, got {type(hostvars).__name__}")

    recorded_by_host: dict[str, dict[str, str]] = {}
    resolved_by_host: dict[str, list[str]] = {}
    for host in hosts:
        if host not in hostvars:
            raise AnsibleFilterError(f"deploy_report: '{host}' is not in hostvars")
        recorded_by_host[host] = _recorded(host, hostvars[host])
        resolved_by_host[host] = _resolved(host, hostvars[host])

    if not any(recorded_by_host.values()):
        return {}

    report: dict[str, dict[str, list[str]]] = {}
    for host in hosts:
        statuses = dict(recorded_by_host[host])
        for name in resolved_by_host[host]:
            statuses.setdefault(name, "unfinished")
        by_outcome = {outcome: [name for name, status in statuses.items() if status == outcome] for outcome in OUTCOMES}
        grouped = {outcome: names for outcome, names in by_outcome.items() if names}
        if grouped:
            report[host] = grouped
    return report


class FilterModule:
    def filters(self):
        return {"deploy_report": deploy_report}
