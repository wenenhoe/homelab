# Deployment Flow

`deploy.yaml` runs as four ordered plays, deliberately sequenced so DNS and the reverse proxy are already serving before anything that depends on them starts.

## Play 1 — System setup (`hosts: all`)

Prompts for the secrets/inputs the rest of the run needs (`main_domain`, DigitalOcean API key, Let's Encrypt email, Diun's Telegram token/chat ID, Wetty's default SSH host, Tinyauth's LDAP observer password), installs Docker Engine, and resolves every host's `compose_apps` against the central `app_registry` (see below). No containers start yet.

## Play 2 — Deploy Caddy (`hosts: all`)

Every host renders its own `Caddyfile`, builds the custom Caddy image (with the DigitalOcean DNS plugin baked in), and starts/restarts its Caddy container — so routing is live before any backend app comes up behind it. Details: [`caddy.md`](caddy.md).

## Play 3 — Configure BIND9 (`hosts: dns`)

Runs only on the `services` host. Scrapes `dns_zones` from every host in `app_hosts`, renders zone files and `named.conf`, deploys the BIND9 container, then repoints the host's own DNS resolution (`systemd-resolved` + Docker daemon) at it. Details: [`bind9.md`](bind9.md).

## Play 4 — Deploy Compose apps (`hosts: all`)

Every remaining app (everything except `caddy` and `bind9`, which already deployed themselves in Plays 2–3) gets its directories/configs provisioned and its container started, now that DNS is resolving and Caddy is routing.

## Ansible Roles

| Role | Purpose |
| :--- | :--- |
| `apt` | Asserts a Debian-family OS, updates and upgrades apt packages, reboots if the kernel/packages require it. |
| `fwupd` | Refreshes firmware metadata, applies available firmware updates via `fwupdmgr`, reboots if a capsule requires it. |
| `docker` | Installs Docker Engine + Compose plugin from Docker's official apt repo (DEB822 format), enables the service, adds `docker_users` to the `docker` group. |
| `compose` | The reusable building block every app deployment goes through: `preinit.yaml` resolves `compose_apps` against the `app_registry` once per host; `init.yaml` creates an app's directories, copies its `compose*.yaml`/scripts, and renders its config templates; `deploy.yaml` pulls/builds images and brings the stack up (and force-restarts it when told a non-compose config file changed). |
| `compose_app` | Batch-drives `compose`'s `init` + `deploy` for every app that isn't self-managed (i.e. everything except `caddy`/`bind9`). |
| `caddy` | Renders the `Caddyfile`, builds a custom Caddy image with the DigitalOcean DNS plugin, and deploys/restarts the proxy. |
| `bind9` | Aggregates DNS zone data from every app host and renders/deploys the authoritative DNS server, then rewires the host's own resolution to use it. |

## The App Registry

`group_vars/all.yaml` defines `app_registry`: a single source of truth for everything about an app that does **not** vary per host — directories to create, scripts/config templates to render, and its Caddy upstream/auth behavior. A `configs` entry is how any templated file (including `.env` files) gets rendered; `force: false` is used for anything containing secrets so a re-run never clobbers what's already on disk.

Each `host_vars/<host>.yaml` then only needs to say *which* apps that host runs and, for routable apps, what hostname(s) to expose them under:

```yaml
compose_apps:
  - name: dashy
    caddy:
      default:
        host: dashy
```

During Play 1, `compose`'s `preinit.yaml` task merges each host's short `compose_apps` entries with their full definition from `app_registry` (`registry_defaults | combine(item, recursive=True)`) and replaces `compose_apps` in `hostvars` with the fully-resolved list. Every downstream role — `caddy`'s Caddyfile template, `bind9`'s zone-file template, `compose_app`'s batch deploy — reads only the resolved list, so an app's routing/upstream/auth logic is defined exactly once regardless of how many hosts run it.

See [`adding-an-app.md`](adding-an-app.md) for a worked example of adding a new entry to the registry.
