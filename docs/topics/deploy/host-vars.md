# `host_vars`: Per-Host Configuration Reference

Each file under `ansible/inventory/host_vars/<host>.yaml` holds everything
about a host that varies per host, as opposed to `app_catalog` (what
doesn't). Field-by-field reference; see
[`adding-an-app.md`](adding-an-app.md) for the worked flow and
[`bind9.md`](../services/bind9.md) for how `dns_zones` becomes DNS records.

| Field | Set on | Purpose |
| :--- | :--- | :--- |
| [`caddy_domain`](#caddy_domain) | hosts running Caddy | the wildcard domain the host's apps are served under |
| [`compose_apps`](#compose_apps) | every app host | the apps it runs and their hostnames |
| [`<app>_host` aliases](#per-host-alias-variables-eg-cobalt_host-shlink_short_host-lldap_host) | some | one hostname label used in two places |
| [`dns_zones`](#dns_zones) | every `app_hosts` member | zones the host contributes records to |
| [anything one host consumes](#single-host-config-and-secrets) | the consuming host | config and secrets no other host reads |

## `caddy_domain`

The wildcard domain this host's Caddy instance terminates TLS for and routes under, e.g. `"svc.{{ lan_domain }}"`. Every routable app on the host gets `<host-label>.<caddy_domain>` as its externally-reachable name — both for Caddy's own routing and for the CNAME BIND9 generates for it.

## `compose_apps`

The list of apps this host runs. Each entry needs only:

- `name` — must match a key in `app_catalog`.
- `routes` (routable apps only) — one block per route (`default`, or a
  descriptive key for multi-route apps, see `adding-an-app.md`'s shlink
  example), each supplying `host: <label>`. Merged with the matching
  `routes` block in `app_catalog` (which supplies `upstream` and
  optionally `auth: false`): the catalog defines *how* to reach the app,
  `host_vars` defines *what to call it* on this host.

Apps with no `routes` block (e.g. `bind9`, `beszel-agent`) are non-routable.

```yaml
compose_apps:
  - name: dashy
    routes:
      default:
        host: dashy       # -> dashy.<caddy_domain>
```

`resolved_apps` (`group_vars/all/main.yaml`) resolves this short form against
`app_catalog` into a full definition, which every downstream role (`caddy`,
`bind9`, `compose_app`, `cleanup.yaml`) reads. `compose_apps` itself stays as
written here.

## Per-host alias variables (e.g. `cobalt_host`, `shlink_short_host`, `lldap_host`)

A handful of hosts define a plain variable for an app's hostname label
(`cobalt_host: cobalt`, ...) instead of writing the label inline twice.
It's referenced both in `compose_apps`'s `routes.<route>.host` and
elsewhere that needs the same hostname — e.g. `step_ca_cert`
(`ansible/roles/step_ca_cert/tasks/main.yaml`, called with
`step_ca_cert_common_name: "{{ lldap_host }}"` for lldap's instance)
builds lldap's cert SAN from `{{ lldap_host }}.{{ caddy_domain }}`, the
same expression Caddy's
own route uses — so Caddy's route and the cert's own SAN can't drift
apart. Only needed for apps whose own config, or something deployed
alongside them, must know its externally-routed hostname.

## `dns_zones`

Relevant on every `app_hosts` member (BIND9 aggregates these from all of
them, not just the `dns` host). Full detail in [`bind9.md`](../services/bind9.md);
briefly:

- `dns_zones` — one entry per zone this host contributes records to (usually just `caddy_domain` itself), with SOA/TTL details and any `extra_records` that aren't auto-derived from `compose_apps` (e.g. the zone's own `NS`/`A` glue records, or a hand-written CNAME like `security.yaml`'s `sso`).

## Single-host config and secrets

`host_vars` also holds config and secrets that only one host consumes, such as `storage.yaml`'s `cloud_sync_targets` or `security.yaml`'s `step_ca_password`. [`secrets.md`](../security/secrets.md) has the rule for choosing between here and `group_vars/all/main.yaml`, with worked examples.

## Excerpt (from `ansible/inventory/host_vars/services.yaml`)

Trimmed to the parts that illustrate each field above — see the real
file for the host's full app list.

```yaml
caddy_domain: "svc.{{ lan_domain }}"

cobalt_host: cobalt

compose_apps:
  - name: caddy
  - name: bind9
  - name: cobalt
    routes:
      default:
        host: "{{ cobalt_host }}"
  # ...rest of this host's apps

dns_zones:
  - zone: "{{ caddy_domain }}"
    ttl: 3600
    soa_email: "hostmaster.{{ main_domain }}."
    serial: 2024010101   # overwritten at render time by the role
    extra_records:
      - { name: "@", type: NS, value: "ns1.{{ caddy_domain }}." }
      - { name: "ns1", type: A, value: "127.0.0.1" }
```
