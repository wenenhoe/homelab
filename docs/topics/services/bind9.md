# BIND9: Internal DNS

The `bind9` role runs an authoritative, non-recursive nameserver on the `services` host (`hosts: dns` in `deploy.yaml`) that serves every app host's internal zones. `storage`, the inventory's `dns_secondary` group, runs the same role as a [secondary](#a-secondary) for all of them, one host after the other in the same play.

## How zone data is gathered

BIND9 itself carries no zone configuration — each app host declares its
own `dns_zones` in `host_vars/*.yaml` (SOA/TTL, `soa_email`, static
`extra_records`). The role loops over `app_hosts`, flattens every declared
zone into one list (`bind9_all_zones`), tagging each with that host's
`host_fqdn` and `caddy_domain`. `host_fqdn` is the same expression for every
host, `<inventory host name>.<host_domain>.`, set once in
`group_vars/all/main.yaml`. See [`host-vars.md`](../deploy/host-vars.md).

## The host zone

`services` also serves `host_domain` (`internal.<main_domain>`), a sibling
of `lan_domain`. It holds one static `A` record for each host the lab
runs: the four app hosts, `tailscale`, the Proxmox node `pve` and the
gateway `opnsense`. They are the `extra_records` of a zone declared in
`host_vars/services.yaml`, like any other zone. Each address repeats the
host's reservation on the gateway, so a reservation that changes there
needs the same change in that file. The role generates no CNAME into this
zone, since none of its names is a Caddy route; every CNAME it generates
elsewhere points at a name in it, the host's `host_fqdn`.

The gateway's resolver forwards the host zone and the `lan_domain` zones
to `services`. It holds no zone and registers no record, so a host has a
name only when it has a record here, and a DHCP client in the gateway's
dynamic pool has none.

## A secondary

The role takes its mode from the inventory, not from a variable on the
host: `bind9_secondary` is true on a host in `dns_secondary` and false on
every other host that runs the role, and `bind9_transfers_enabled` is true
on both once that group has a member.

The secondary renders no zone file. It declares each zone in
`bind9_all_zones` (the list the primary renders from) as `type secondary`,
taken from `dns_primary_address` over the transfer key, and keeps what it
receives in `/var/lib/bind`, the `records` volume, which the role hands to the `bind` user
before the container starts, since a new volume belongs to root. A restart therefore
serves the zones it already holds without reaching the primary, while a
secondary that has never completed a transfer answers `SERVFAIL` for them.

The key is the `dns-transfer-key` catalog entry (`hosts/all/dns`). It is 64
hex characters, which BIND reads as the base64 secret of an `hmac-sha256`
key, and the role renders it to `named.conf.key` on both hosts at mode
`0640` for `bind:bind`, in its own task with `no_log`. With a secondary
declared, the primary's `allow-transfer` names that key alone and it
notifies `dns_secondary_address`, so a transfer without the key or under
another secret is refused. With none declared it keeps
`allow-transfer { none; }` and renders no key.

A change to a zone reaches the secondary within seconds: the primary
restarts on a real change, sends a NOTIFY, and the secondary pulls the zone
over a signed transfer. The NOTIFY is unsigned; the transfer that follows is
not. The zone serial changes only with a zone's content
([below](#serial-handling-without-spurious-reloads)), so the secondary
transfers only a zone that really changed.

## Template outputs per run

- **`named.conf.j2`** — the options, which differ by mode (see above).
- **`named.conf.key.j2`** — the transfer key, rendered only once a secondary
  is declared.
- **`named.conf.local.j2`** — one zone block per entry in `bind9_all_zones`:
  `type master` on the primary, `type secondary` on a secondary.
- **`zone.db.j2`** — on the primary only, each zone's SOA header, static
  `extra_records`, and **auto-generated CNAMEs**: for every app with a `routes` entry whose
  hostname falls inside the zone, it emits a CNAME pointing at that
  host's `host_fqdn`. Adding `routes: { default: { host: foo } }` to
  an app in `host_vars` gets it both a routing rule and a DNS record, no
  manual zone editing.

## Serial handling without spurious reloads

A fresh Unix-epoch serial is computed every run, but zone files are
compared against the live file with the serial line stripped first — a
zone is only written and BIND only reloaded when the real content
changed:

1. Render each zone's candidate content in-memory via the `template` lookup — no side-car files touch disk for the comparison itself.
2. Read back whatever's currently live on disk, if anything, via `slurp` (a missing file is expected on first run, not an error).
3. Strip the serial line from both in Jinja and compare; only write the file (via `copy`, which then reports `changed` accurately) when the non-serial content actually differs.

## Self-managed deploy ordering

Like `caddy`, `bind9` deploys and restarts its own compose stack directly
rather than through the generic `compose_app` batch role, since its final
step repoints the host's own DNS resolution at the container it just
started:

- Disables `systemd-resolved`'s stub listener, relinks `/etc/resolv.conf`
  to the upstream resolver.
- Writes `/etc/docker/daemon.json` with explicit upstream DNS servers, so
  Docker doesn't depend on the container it's about to route through.

Both applied via handlers (`Restart systemd-resolved`, `Restart docker`)
so they only fire on change.

It also seeds its own `config` volume directly rather than through
`compose_app`'s generic staging: renders `named.conf`/zone files to
`bind9_config_dir`, then reuses `seed_volume.yaml` directly, gated on
`bind9_dns_changed`. See [`volumes.md`](../deploy/volumes.md).

Zone/config rendering and image pull/deploy are independently taggable:
`--tags infra` re-renders and reloads DNS data without touching the
image; `--tags images` redeploys without touching DNS data. See
[`deployment-flow.md`](../deploy/deployment-flow.md#tags).

## Runtime config

`docker/bind9/compose.yaml.j2`: `ubuntu/bind9` runs as a dedicated
`bind:bind` user/group (uid/gid `9970`), binds `53/tcp` and `53/udp` on
all interfaces, and mounts four volumes: `config` (seeded when
`bind9_dns_changed`, see [`volumes.md`](../deploy/volumes.md)) plus
`cache`/`records`/`run` for BIND's own state. Recursion is disabled — it
only answers authoritatively for its own zones. While no secondary is
declared `allow-transfer { none; }` refuses zone transfers; once one is, only
the transfer key may transfer ([above](#a-secondary)).
