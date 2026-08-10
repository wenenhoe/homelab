# `host_vars`: Per-Host Configuration Reference

Each file under `ansible/inventory/host_vars/<host>.yaml` holds everything
about a host that varies per host, as opposed to `app_registry` (what
doesn't). Field-by-field reference; see
[`adding-an-app.md`](adding-an-app.md) for the worked flow and
[`bind9.md`](bind9.md) for how `dns_zones` becomes DNS records.

## `caddy_domain`

The wildcard domain this host's Caddy instance terminates TLS for and routes under, e.g. `"svc.{{ lab_domain }}"`. Every routable app on the host gets `<host-label>.<caddy_domain>` as its externally-reachable name — both for Caddy's own routing and for the CNAME BIND9 generates for it.

## `compose_apps`

The list of apps this host runs. Each entry needs only:

- `name` — must match a key in `app_registry`.
- `caddy` (routable apps only) — one block per route (`default`, or a
  descriptive key for multi-route apps, see `adding-an-app.md`'s shlink
  example), each supplying `host: <label>`. Merged with the matching
  `caddy` block in `app_registry` (which supplies `upstream` and
  optionally `auth: false`): the registry defines *how* to reach the app,
  `host_vars` defines *what to call it* on this host.

Apps with no `caddy` block (e.g. `bind9`, `diun`) are non-routable.

```yaml
compose_apps:
  - name: dashy
    caddy:
      default:
        host: dashy       # -> dashy.<caddy_domain>
```

At Play 1 (`compose`'s `preinit.yaml`), this short form resolves against
`app_registry` into a full definition and is written back into
`hostvars`, which every downstream role (`caddy`, `bind9`, `compose_app`,
`cleanup.yaml`) reads.

## Per-host alias variables (e.g. `cobalt_host`, `shlink_short_host`, `lldap_host`)

A handful of hosts define a plain variable for an app's hostname label
(`cobalt_host: cobalt`, ...) instead of writing the label inline twice.
It's referenced both in `compose_apps`'s `caddy.<route>.host` and in that
app's own `configs/*.j2` (e.g. `docker/lldap/configs/env.j2` builds
`LDAP_DOMAIN` from `{{ lldap_host }}.{{ caddy_domain }}`), so Caddy's
route and the app's self-reported URL can't drift apart. Only needed for
apps whose own config must know its externally-routed hostname.

## `dns_ddns_target` / `dns_zones`

Relevant on every `app_hosts` member (BIND9 aggregates these from all of
them, not just the `dns` host). Full detail in [`bind9.md`](bind9.md);
briefly:

- `dns_ddns_target` — the OPNsense DDNS name this host resolves to; every auto-generated CNAME for this host's apps points here.
- `dns_zones` — one entry per zone this host contributes records to (usually just `caddy_domain` itself), with SOA/TTL details and any `extra_records` that aren't auto-derived from `compose_apps` (e.g. the zone's own `NS`/`A` glue records, or a hand-written CNAME like `security.yaml`'s `sso`).

## Excerpt (from `ansible/inventory/host_vars/services.yaml`)

Trimmed to the parts that illustrate each field above — see the real
file for the host's full app list.

```yaml
caddy_domain: "svc.{{ lab_domain }}"

cobalt_host: cobalt

compose_apps:
  - name: caddy
  - name: bind9
  - name: cobalt
    caddy:
      default:
        host: "{{ cobalt_host }}"
  # ...rest of this host's apps

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
