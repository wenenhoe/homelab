# Adding an App

New apps are wired in through three places: a `docker/<app>/` directory, an `app_registry` entry, and a `compose_apps` entry on whichever host(s) should run it.

## 1. Add `docker/<app>/`

Create a directory holding the app's Compose stack:

```
docker/<app>/
├── compose.yaml          # Required
└── configs/               # Optional — Jinja2 templates rendered onto the host
    └── env.j2
```

- `compose.yaml` is copied as-is to `{{ compose_deploy_dir }}/<app>/` on the target host.
- Anything in `configs/` is rendered through Ansible's `template` module (so it can reference any Ansible variable, e.g. `{{ server_timezone }}`) and written to whatever `dest` its `app_registry` entry specifies — this is also how `.env` files are generated.

## 2. Register it in `app_registry`

In `ansible/inventory/group_vars/all/app_registry.yaml`, add an entry keyed by the app name. This is the single source of truth for everything about the app that doesn't vary per host:

```yaml
app_registry:
  my-app:
    volumes:
      - name: data
    configs:
      - src: env.j2
        dest: .env
        mode: "0600"
        no_log: true      # if this .env holds a real secret — see below
    caddy:
      default:
        upstream: "my-app:8080"
```

- `volumes`: named Docker volumes Ansible creates and (if there's existing data at the old bind-mount path) migrates into automatically — this is what `./data:/data` in `compose.yaml` becomes `data:/data` plus a `volumes: { data: { external: true, name: my-app_data } }` block referencing. See [`volumes.md`](volumes.md) for the full mechanism, including how to seed Ansible-rendered configs into one. Omit entirely for an app with no persistent state, or if you'd rather keep a plain bind mount for now (e.g. an experimental stack) — `create_dirs` below still works unmodified either way.
- `create_dirs`: subdirectories created under `{{ compose_deploy_dir }}/<app>/` before the stack starts — only needed for content that stays a bind mount (or a staging path a volume gets seeded from), since a declared `volumes` entry no longer needs its directory pre-created.
- `configs`: templates to render. Every config defaults to `force: true` (overwrite when content differs — this repo is the source of truth) and needs no `force` key at all unless the destination can hold real state Ansible has no way to reconstruct, e.g. an in-app settings UI that writes back to the same file (see `dashy`'s `app_registry` entry for a live example of this open question). If a config renders a real secret (an API key, token, or password — not just a hostname or timezone), set `no_log: true` on it, or a run with `--diff` prints the plaintext straight to the console the moment its value ever differs from what's already deployed, including on the very first deploy — see [`secrets.md`](secrets.md)'s "`no_log: true`" note. If the config needs a secret this repo can generate itself (an API key, a bind password, ...), add it to `ansible/inventory/group_vars/all/secrets_registry.yaml` rather than calling `lookup('password', ...)`/`lookup('pipe', ...)` directly in the template.
- `scripts`: any helper scripts to copy verbatim into `<app>/scripts/`.
- `caddy`: omit entirely for an app with no HTTP frontend. For a routable app, each key (`default`, or a descriptive name for apps with multiple routes — see `shlink`'s `short`/`web` pattern) needs an `upstream` (`container:port`) and, optionally, `auth: false` to skip the Tinyauth forward-auth step.

## 3. Add it to a host's `compose_apps`

In the relevant `ansible/inventory/host_vars/<host>.yaml`, add a minimal entry with just the app name, plus a `caddy` block supplying the hostname if it's routable:

```yaml
compose_apps:
  - name: my-app
    caddy:
      default:
        host: my-app
```

At deploy time, this gets merged with the `app_registry` entry (`registry_defaults | combine(item, recursive=True)`), so the fully-resolved app carries both its registry defaults and its host-specific hostname. If the host is in `app_hosts` (`services`, `play`, `security`, `storage` — every host in the `prod` group; `experiment` isn't), a CNAME for `my-app.{{ caddy_domain }}` is generated automatically, with no manual DNS editing required. See [`host-vars.md`](host-vars.md) for the full `host_vars` field reference, including the alias-variable pattern (`cobalt_host`, `lldap_host`, ...) used when an app's own config needs to know its routed hostname too.

## 4. Deploy

```sh
ansible-playbook deploy.yaml --limit <host>
```

The app is picked up by Play 4 (`compose_app` role), which provisions its directories/config and starts the stack, after Caddy and BIND9 are already routing/resolving for it.

## Multi-route apps

Some apps front more than one container behind two different hostnames (e.g. `shlink`, which pairs a redirector and a web UI). Give each route its own key under `caddy` in both the registry entry and the host's `compose_apps` entry — the key just needs to match between the two:

```yaml
# app_registry
shlink:
  caddy:
    short:
      upstream: "shlink:8080"
    web:
      upstream: "shlink-web-client:8080"

# host_vars
compose_apps:
  - name: shlink
    caddy:
      short:
        host: short
      web:
        host: shlink
```
