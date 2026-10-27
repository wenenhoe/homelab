# BIND9: Internal DNS

The `bind9` role runs a single authoritative, non-recursive nameserver on the `services` host (`hosts: dns` in `deploy.yaml`) that serves every app host's internal zones.

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

## Two template outputs per run

- **`named.conf.local.j2`** — one `zone { type master; ... }` block per
  entry in `bind9_all_zones`.
- **`zone.db.j2`** — each zone's SOA header, static `extra_records`, and
  **auto-generated CNAMEs**: for every app with a `routes` entry whose
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
only answers authoritatively for its own zones, and `allow-transfer { none; }`
refuses zone transfers, as no secondary server exists.
