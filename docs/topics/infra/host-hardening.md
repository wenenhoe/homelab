# Host Hardening Baseline

OS-level hardening applied to hosts that already run this repo's own
roles. [ADR 0043](../../decisions/0043-host-os-hardening-baseline/revision-000.md)
holds the reasoning, the collisions with this repo's roles that set the
order areas can be added in, and the rules for adding one.

## Shape

The `host_hardening` role (`ansible/roles/host_hardening/tasks/main.yaml`)
includes roles from the pinned `konstruktoid.hardening` collection. Its
tasks file is the allow-list: one include per area, and no area runs
unless it is included there. The collection is never applied whole.

The pin is in `ansible/requirements.yml` and, for Molecule, in
`ansible/roles/molecule_helpers/requirements.yml`, together with
`community.general`. A change to either file queues every role's
Molecule scenario, so a bump reruns each included area's scenario.

## Areas

| Area | Effect |
| :--- | :--- |
| `automatic_updates` | `unattended-upgrades` is installed with periodic updates on, only security origins allowed, and no automatic reboot. The role passes the whole `automatic_updates` dict rather than relying on the collection's defaults, so a version bump cannot change it. |

Reboots and firmware stay in `maintenance.yaml` (`apt` and `fwupd`).

## Where it is applied

`playbooks/maintenance.yaml` runs the role on every `patched_hosts`
member in its last play, after the update play, so a failure there
cannot block patching. `maintenance.yaml` is the one playbook that
reaches both `managed_hosts` and `network_infra`; see
[`network-infra.md`](network-infra.md).

Hosts outside `patched_hosts` include the role from their own builds.

## Verifying a host

The effective configuration is what counts, not the drop-in files:

```sh
apt-config dump APT::Periodic | grep -E 'Update-Package-Lists|Unattended-Upgrade'
apt-config dump Unattended-Upgrade | grep -E 'Allowed-Origins|Reboot|updates'
```

Both periodic values are `"1"`, no allowed origin is an `-updates`
pocket, and no `Automatic-Reboot "true"` appears. The role's Molecule
scenario asserts the same lines; see
[`molecule-testing.md`](../engineering/molecule-testing.md).

## Adding an area

One change per area, as the ADR's Decision sets out: include the role in
the tasks file, set the variables this repo needs, add or extend a
Molecule scenario that asserts the area's effect and passes idempotence,
and resolve any collision with this repo's own roles in the same change.
