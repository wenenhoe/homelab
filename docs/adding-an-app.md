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

In `ansible/group_vars/all.yaml`, add an entry keyed by the app name. This is the single source of truth for everything about the app that doesn't vary per host:

```yaml
app_registry:
  my-app:
    create_dirs:
      - data
    configs:
      - src: env.j2
        dest: .env
        mode: "0600"
        force: false      # never clobber a rendered .env that may hold secrets
    caddy:
      default:
        upstream: "my-app:8080"
```

- `create_dirs`: subdirectories created under `{{ compose_deploy_dir }}/<app>/` before the stack starts (e.g. bind mounts for persistent data).
- `configs`: templates to render; `force: false` is standard for anything containing secrets so re-runs don't overwrite what's already on disk.
- `scripts`: any helper scripts to copy verbatim into `<app>/scripts/`.
- `caddy`: omit entirely for an app with no HTTP frontend. For a routable app, each key (`default`, or a descriptive name for apps with multiple routes — see `shlink`'s `short`/`web` pattern) needs an `upstream` (`container:port`) and, optionally, `auth: false` to skip the Tinyauth forward-auth step.

## 3. Add it to a host's `compose_apps`

In the relevant `ansible/host_vars/<host>.yaml`, add a minimal entry with just the app name, plus a `caddy` block supplying the hostname if it's routable:

```yaml
compose_apps:
  - name: my-app
    caddy:
      default:
        host: my-app
```

At deploy time, this gets merged with the `app_registry` entry (`registry_defaults | combine(item, recursive=True)`), so the fully-resolved app carries both its registry defaults and its host-specific hostname. If the host also runs `bind9` (or is in `app_hosts`, which all hosts are), a CNAME for `my-app.{{ caddy_domain }}` is generated automatically, with no manual DNS editing required. See [`host-vars.md`](host-vars.md) for the full `host_vars` field reference, including the alias-variable pattern (`cobalt_host`, `lldap_host`, ...) used when an app's own config needs to know its routed hostname too.

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
