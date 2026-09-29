"""app_deploy_plan: split an app's configs and scripts into direct and volume-seeded.

roles/compose/tasks/init.yaml deploys each config and script one of two
ways. One whose destination starts at a volume the app declares is staged
on the host and seeded into that volume; every other one is written
straight to the host. This filter makes that decision for one app and
returns both lists for each kind, in input order:

    {"configs": {"direct": [...], "seeded": [...]},
     "scripts": {"direct": [...], "seeded": [...]}}

A seeded config is the original config plus `volume_name` and
`volume_relpath`. A script is a bare name; it is seeded into the app's
`scripts` volume when it declares one, and otherwise deployed directly to
`scripts/<name>`. A missing or null `volumes`, `configs` or `scripts` is
empty. The input is never modified.
"""

from __future__ import annotations

from ansible.errors import AnsibleFilterError


def _items(app: dict, key: str) -> list:
    value = app.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise AnsibleFilterError(f"app_deploy_plan: '{key}' of app '{app.get('name', '?')}' must be a list, got {type(value).__name__}")
    return value


def app_deploy_plan(app: dict) -> dict:
    """Classify `app`'s configs and scripts as direct or volume-seeded."""
    if not isinstance(app, dict):
        raise AnsibleFilterError(f"app_deploy_plan: expected an app mapping, got {type(app).__name__}")
    name = app.get("name", "?")
    volume_names = []
    for volume in _items(app, "volumes"):
        if not isinstance(volume, dict) or "name" not in volume:
            raise AnsibleFilterError(f"app_deploy_plan: a volume of app '{name}' has no 'name': {volume}")
        volume_names.append(volume["name"])
    plan = {"configs": {"direct": [], "seeded": []}, "scripts": {"direct": [], "seeded": []}}

    for config in _items(app, "configs"):
        if not isinstance(config, dict) or not isinstance(config.get("dest"), str):
            raise AnsibleFilterError(f"app_deploy_plan: a config of app '{name}' has no string 'dest': {config}")
        volume_name, separator, relpath = config["dest"].partition("/")
        if volume_name not in volume_names:
            plan["configs"]["direct"].append(config)
        elif not separator:
            raise AnsibleFilterError(
                f"app_deploy_plan: config dest '{config['dest']}' of app '{name}' names the volume '{volume_name}' itself; "
                f"give it a path inside the volume, e.g. '{volume_name}/<file>'"
            )
        else:
            plan["configs"]["seeded"].append({**config, "volume_name": volume_name, "volume_relpath": relpath})

    scripts_seeded = "scripts" in volume_names
    for script in _items(app, "scripts"):
        if scripts_seeded:
            plan["scripts"]["seeded"].append({"src": script, "volume_name": "scripts", "volume_relpath": script})
        else:
            plan["scripts"]["direct"].append({"src": script, "dest": f"scripts/{script}"})

    return plan


class FilterModule:
    def filters(self):
        return {"app_deploy_plan": app_deploy_plan}
