# Network Infrastructure Hosts

Hosts that support the network itself rather than running Docker/
compose apps — the `network_infra` inventory group. Currently one
host: `tailscale` (VM 202), an existing Tailscale subnet router
brought under Ansible management for
[`monitoring-host-isolation.md`](../../projects/monitoring-host-isolation.md); see
[`off-site-monitoring.md`](../../projects/off-site-monitoring.md) for why (offsite
monitoring's eventual off-site hop reuses this VM's existing route rather
than a new tunnel).

## Why its own group, not `managed_hosts`

`managed_hosts` gets Docker, the `compose`/`compose_app` roles, and
every app-deploy play in `deploy.yaml`. VM 202 runs none of that — it's
a routing appliance, not an app host — so folding it into
`managed_hosts` would mean either deploying Docker to a VM that has no
use for it, or complicating every `deploy.yaml` play with a new
exclusion. `network_infra` stays out of `deploy.yaml` entirely;
`patched_hosts` (an alias of `managed_hosts` + `network_infra`, same
pattern as `app_hosts`) is what `maintenance.yaml` targets instead —
see [`ansible.md`](../deploy/ansible.md#inventory).

## Future: superseded by Tofu

The `tailscale` entry is interim: [`tofu-vm-provisioning.md`](../../projects/tofu-vm-provisioning.md)
rebuilds VM 202 as a Tofu-managed VM, and its inventory generator then
produces this host's entry. Remove the hand-written block from
`inventory.yaml` at that point rather than keeping both.

## `tailscale` (VM 202) — current state

Read directly off the host, not assumed:

| Field | Value |
| :--- | :--- |
| OS | Ubuntu LTS (`resolute`) |
| Tailscale | Installed from the official apt repo (`pkgs.tailscale.com/stable/ubuntu resolute`), `tailscaled.service` active |
| Role | Subnet router — advertises `192.168.20.0/24` (`PrimaryRoutes` in `tailscale status --self --json`) |
| DDNS name | `tailscale.{{ ddns_domain }}` — same `<host>.{{ ddns_domain }}` structure as every `managed_hosts` member; this is what `inventory.yaml`'s `ansible_host` actually uses |
| LAN address | `192.168.20.2/24` on `ens18`, DHCP-obtained (`dynamic`, not netplan-static) — descriptive only, `ansible_host` doesn't hardcode this |
| `qemu-guest-agent` | Already installed and active (pre-dates this being under management) |
| SSH admin user | `tsadmin` |

`192.168.20.2` matches the `.02` host-octet [`vm-provisioning.md`'s VMID
scheme](vm-provisioning.md#vmid--vlan--ip-scheme) would predict for
VMID 202 — but that scheme is written for Tofu-provisioned VMs, VM 202
predates Tofu, and the interface shows a DHCP-obtained lease rather
than a static netplan config. Whether Kea holds a MAC-keyed
reservation that makes this address effectively permanent, or it's
coincidence, still hasn't been confirmed — no longer operationally
relevant to `ansible_host` now that it resolves through DDNS the same
as every other host, but relevant to whether this host would ever
belong in `sos-inventory.yaml` (static-IP-only, DNS-independent
recovery path). Not added there yet: `reset-network.yaml`'s whole
reason to exist is reaching a host when DNS itself might be down, and
this host is reachable over its own `tailscale0` interface regardless
of this repo's DNS — whether that makes `sos-inventory.yaml` coverage
redundant or still worth having for netplan-reset specifically is an
open question, not a settled "no."

Per-node Tailscale ACL tags: none found (`tailscale status --self
--json`'s `Self` has no `Tags` key). The tailnet-wide ACL policy itself
— what any node, tagged or not, is actually allowed to reach — is the
default allow-all grant (ADR 0058's Context), held only in the
Tailscale admin console; see
[ADR 0059 (Tailnet policy)](../../decisions/0059-where-the-tailnet-policy-is-defined/revision-000.md)
for where it goes from here.

Re-authenticating this node after a rebuild ([`tofu-vm-provisioning.md`](../../projects/tofu-vm-provisioning.md))
needs an auth key created out of band. An auth key that tags the node on
creation puts it under a `tagOwners` entry in the policy, and a tag is
also what route auto-approval keys off — so the Ansible role's auth-key
handling and ADR 0059's policy-as-code work may not be as separable as
"role first, policy later" suggests. Not resolved yet; check before the
role's auth-key design is written.

## Bringing a new `network_infra` host under management

One-time prerequisites, none of which can be automated
by the same Ansible run that depends on them (the same
chicken-and-egg `bootstrap-secrets.yaml`'s own header describes for
secrets):

1. **SSH key** — add the public half of `~/.ssh/proxmox_vm_servers`
   (the key every `managed_hosts` member already trusts) to the
   admin user's `authorized_keys`.
2. **Passwordless sudo** — `ansible.cfg` sets `become_ask_pass = False`
   and nothing in this repo stores a `become` password anywhere, so
   the admin user needs a `NOPASSWD` sudoers entry before any
   `become: true` task (Play 0's Gathering Facts included) can
   succeed.
3. **Python interpreter** — `inventory.yaml`'s
   `ansible_python_interpreter: /usr/bin/python3.14` is a global
   `all.vars` default; confirm it exists on the host (or override it
   per-host) before the first run.
4. **DDNS name** — confirm one actually exists (`<host>.{{ ddns_domain }}`)
   before assuming a new `network_infra` host needs the static-IP
   fallback pattern instead; `tailscale` has one and uses it.

`tailscale` needed the first three — `tsadmin`'s sudo currently
prompts for a password (`sudo -n true` fails with
"interactive authentication is required"), and not the fourth.

## Verifying

```sh
ansible-playbook playbooks/maintenance.yaml --limit patched_hosts,localhost
```

Runs `apt`/`fwupd` against every `patched_hosts` member,
`qemu_guest_agent` against `network_infra` only, and then the
`host_hardening` baseline against every `patched_hosts` member. No
`deploy.yaml` equivalent exists for this group — see "Why its own group"
above.
