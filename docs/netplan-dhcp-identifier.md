# Netplan DHCP Client Identifier

Current fleet only — `services`/`play`/`security`/`storage` each carry
a hand-applied netplan override forcing a single DHCP client
identifier across boot phases, working around a dual-lease bug. This
is a transitional fix, not final architecture:
[`projects/tofu-vm-provisioning.md`](projects/tofu-vm-provisioning.md)'s
Migration Stage 2 decommissions these hosts in favor of
Tofu-provisioned VMs with static IPs and no DHCP at all — see
[`vm-provisioning.md`](vm-provisioning.md#ubuntu-vms) for why that
design skips DHCP entirely rather than needing this same fix. Not
Ansible-managed — applied by hand, and not worth automating given
it's headed for replacement.

## The bug

Ubuntu 26.04's boot has two distinct network-initialization phases,
each using a different DHCP client identifier: dracut's initramfs
config (`zzzz-dracut-default.network`) identifies by MAC, netplan's own
OS-phase config (`10-netplan-ens18.network`) identifies by DUID.
OPNsense's Kea DHCP server treats the two identifiers as different
clients, so it can't correlate the OS-phase request as a renewal of
the initramfs lease — it issues a second, different IP instead of
renewing the first. The first lease is never explicitly released.
Kea's DDNS-push then fails outright: it tries to replace the A record
it wrote for the first IP with the second, but by the time it attempts
that, the record no longer matches what it expects (`RCODE: 8`,
NXRRSET).

## The fix

Force both boot phases onto the same DHCP client identifier —
Netplan's `dhcp-identifier: mac` makes the OS-phase request use MAC
too, so Kea sees a renewal instead of a new client:

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    ens18:
      dhcp4: true
      dhcp-identifier: mac
```

Same IP both times; the DDNS update succeeds. Placed by hand at
`/etc/netplan/01-netcfg.yaml` on each of `services`/`play`/`security`/
`storage`.
