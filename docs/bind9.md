# BIND9: Internal DNS

The `bind9` role runs a single authoritative, non-recursive nameserver on the `services` host (`hosts: dns` in `deploy.yaml`) that serves every app host's internal zones.

## How zone data is gathered

BIND9 itself carries no zone configuration — each app host declares its own `dns_zones` in its `host_vars/*.yaml` (SOA/TTL, `soa_email`, and any static `extra_records`). The role loops over the `app_hosts` group, reaches into each host's `hostvars`, and flattens every declared zone into one list (`bind9_all_zones`), tagging each entry with that host's `dns_ddns_target` and `caddy_domain`. See [`host-vars.md`](host-vars.md) for the full field reference.

## Two template outputs per run

- **`named.conf.local.j2`** declares one `zone { type master; ... }` block per entry in `bind9_all_zones`.
- **`zone.db.j2`** renders each zone's actual records: the SOA header, any static `extra_records` from `host_vars`, and **auto-generated CNAMEs**. It walks that host's resolved `compose_apps`, and for every app with a `caddy` route whose hostname (`<host>.<caddy_domain>`) falls inside the zone being rendered, it emits a CNAME pointing at that host's `dns_ddns_target`. In other words, adding `caddy: { default: { host: foo } }` to an app in `host_vars` is enough for it to get both a working reverse-proxy route *and* a DNS record, without any manual zone editing.

## Serial handling without spurious reloads

A fresh Unix-epoch serial is computed on every run, but zone files are compared against the live file *with the serial line stripped out* first; a zone is only written (and BIND only reloaded) when the real content changed, not just the epoch. The strategy:

1. Render each zone's candidate content in-memory via the `template` lookup — no side-car files touch disk for the comparison itself.
2. Read back whatever's currently live on disk, if anything, via `slurp` (a missing file is expected on first run, not an error).
3. Strip the serial line from both in Jinja and compare; only write the file (via `copy`, which then reports `changed` accurately) when the non-serial content actually differs.

## Self-managed deploy ordering

Like `caddy`, the `bind9` role deploys and restarts its own compose stack directly (via the `compose` role's `deploy.yaml` tasks) rather than going through the generic `compose_app` batch role. This matters because the role's final step repoints the host's own DNS resolution at the container it just started:

- Disables `systemd-resolved`'s stub listener and relinks `/etc/resolv.conf` to the upstream resolver.
- Writes `/etc/docker/daemon.json` with explicit upstream DNS servers, so the Docker daemon itself doesn't depend on the container it's about to route through.

Both changes are applied via handlers (`Restart systemd-resolved`, `Restart docker`) so they only fire when something actually changed.

Being self-managed also means `bind9` seeds its own `config` volume directly rather than going through `compose_app`'s generic registry-driven staging: it renders `named.conf`/`named.conf.local`/zone files straight to a staging path it controls (`bind9_config_dir`), then reuses the `compose` role's `seed_volume.yaml` task directly, gated on `bind9_dns_changed` — the same change flag that decides whether to restart the stack. See [`volumes.md`](volumes.md).

Zone/config rendering and the image pull/deploy are independently taggable — `ansible-playbook deploy.yaml --tags infra` re-renders and reloads DNS data without touching the image, `--tags images` pulls/redeploys without touching DNS data. See the [Tags section in `deployment-flow.md`](deployment-flow.md#tags).

## Runtime config

`docker/bind9/compose.yaml`: the `ubuntu/bind9` image runs as a dedicated system `bind:bind` user/group (uid/gid `9970`, created by the role), binds `53/tcp` and `53/udp` on all interfaces, and mounts four named Docker volumes: `config` (seeded from the staged `named.conf`/`named.conf.local`/zone files above, only when `bind9_dns_changed` is true — see [`volumes.md`](volumes.md)) plus `cache`/`records`/`run` for BIND's own persistent state. Recursion is disabled — it only answers authoritatively for its own zones.
