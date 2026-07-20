# `host_vars`: Per-Host Configuration Reference

Each file under `ansible/host_vars/<host>.yaml` is everything about a host that *does* vary per host — as opposed to `group_vars/all.yaml`'s `app_registry`, which is everything about an app that doesn't. This is a field-by-field reference; see [`adding-an-app.md`](adding-an-app.md) for the worked end-to-end flow and [`bind9.md`](bind9.md) for how `dns_zones` gets turned into actual DNS records.

## `caddy_domain`

The wildcard domain this host's Caddy instance terminates TLS for and routes under, e.g. `"svc.{{ lab_domain }}"`. Every routable app on the host gets `<host-label>.<caddy_domain>` as its externally-reachable name — both for Caddy's own routing and for the CNAME BIND9 generates for it.

## `compose_apps`

The list of apps this host runs. Each entry needs only:

- `name` — must match a key in `app_registry`.
- `caddy` (routable apps only) — one block per route (`default`, or a descriptive key for multi-route apps — see `adding-an-app.md`'s shlink example), each supplying `host: <label>`. This is merged with the matching `caddy` block from that app's `app_registry` entry (which supplies `upstream` and, optionally, `auth: false`), so the registry defines *how* to reach the app and `host_vars` defines *what to call it* on this particular host.

Apps with no `caddy` block at all (e.g. `bind9`, `diun`) are non-routable — nothing to merge, they just get deployed.

```yaml
compose_apps:
  - name: dashy
    caddy:
      default:
        host: dashy       # -> dashy.<caddy_domain>
```

At Play 1 (`compose`'s `preinit.yaml`), this short form is resolved against `app_registry` into a full definition and written back into `hostvars`, which is what every downstream role (`caddy`, `bind9`, `compose_app`, and `cleanup.yaml`) actually reads.

## Per-host alias variables (e.g. `cobalt_host`, `shlink_short_host`, `lldap_host`)

A handful of hosts define a plain variable for an app's hostname label (`cobalt_host: cobalt`, `lldap_host: lldap`, ...) instead of writing the label inline in two places. The variable is referenced both in the `compose_apps` entry's `caddy.<route>.host` **and** in that app's own `configs/*.j2` template (e.g. `docker/lldap/configs/env.j2` builds `LDAP_DOMAIN` from `{{ lldap_host }}.{{ caddy_domain }}`, and `docker/tinyauth/configs/config.yaml.j2` uses the same `lldap_host` to know where to find lldap over LDAPS). Defining it once as a host var, rather than duplicating the literal string, keeps Caddy's route and the app's self-reported URL from silently drifting apart. Not every app needs this — only ones whose own config needs to know its externally-routed hostname.

## `dns_ddns_target` / `dns_zones`

Only relevant on hosts that should get DNS records (in practice, every `app_hosts` member — BIND9 aggregates these from all of them, not just the `dns` host it runs on). Covered in full in [`bind9.md`](bind9.md); briefly:

- `dns_ddns_target` — the OPNsense DDNS name this host resolves to; every auto-generated CNAME for this host's apps points here.
- `dns_zones` — one entry per zone this host contributes records to (usually just `caddy_domain` itself), with SOA/TTL details and any `extra_records` that aren't auto-derived from `compose_apps` (e.g. the zone's own `NS`/`A` glue records, or a hand-written CNAME like `security.yaml`'s `sso`).

## Worked example (`ansible/host_vars/services.yaml`)

```yaml
caddy_domain: "svc.{{ lab_domain }}"

cobalt_host: cobalt
shlink_short_host: short
shlink_web_host: shlink

compose_apps:
  - name: caddy
  - name: bind9
  - name: cobalt
    caddy:
      default:
        host: "{{ cobalt_host }}"
  - name: shlink
    caddy:
      short:
        host: "{{ shlink_short_host }}"
      web:
        host: "{{ shlink_web_host }}"
  - name: diun

dns_ddns_target: "services.{{ ddns_domain }}."
dns_zones:
  - zone: "{{ caddy_domain }}"
    ttl: 3600
    soa_email: "hostmaster.{{ main_domain }}."
    serial: 2024010101   # overwritten at render time by the role
    extra_records:
      - { name: "@", type: NS, value: "ns1.{{ caddy_domain }}." }
      - { name: "ns1", type: A, value: "127.0.0.1" }
```
