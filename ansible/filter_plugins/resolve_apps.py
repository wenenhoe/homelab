"""resolve_apps: lay each host-intent app entry over its catalog definition.

`compose_apps` is a host's intent (which apps, under which hostnames); the
catalog holds what does not vary by host. This filter returns one merged
definition per `compose_apps` entry, in input order. Dicts merge
recursively, so a host's route hostname joins the catalog's route upstream;
a list on the host side replaces the catalog's list outright, which is
`combine(recursive=True)`'s behaviour and what the deployed configs rely
on. An app with no catalog entry resolves to itself. The inputs are never
modified. See ADR 0065.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ansible.errors import AnsibleFilterError
from ansible.utils.vars import merge_hash


def resolve_apps(compose_apps: Sequence[Mapping], app_catalog: Mapping) -> list[dict]:
    """Merge every entry of `compose_apps` over its `app_catalog` definition."""
    if isinstance(compose_apps, (str, bytes)) or not isinstance(compose_apps, Sequence):
        raise AnsibleFilterError(f"resolve_apps: compose_apps must be a list, got {type(compose_apps).__name__}")
    if not isinstance(app_catalog, Mapping):
        raise AnsibleFilterError(f"resolve_apps: the catalog must be a mapping keyed by app name, got {type(app_catalog).__name__}")

    resolved = []
    for app in compose_apps:
        if not isinstance(app, Mapping) or "name" not in app:
            raise AnsibleFilterError(f"resolve_apps: every compose_apps entry needs a 'name', got: {app}")
        defaults = app_catalog.get(app["name"])
        if defaults is None:
            defaults = {}
        elif not isinstance(defaults, Mapping):
            raise AnsibleFilterError(f"resolve_apps: the catalog entry for '{app['name']}' must be a mapping, got {type(defaults).__name__}")
        resolved.append(merge_hash(defaults, app, recursive=True, list_merge="replace"))
    return resolved


class FilterModule:
    def filters(self):
        return {"resolve_apps": resolve_apps}
