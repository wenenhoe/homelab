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

- `volumes`: named Docker volumes Ansible creates and migrates existing bind-mount data into (`./data:/data` becomes `data:/data`). See [`volumes.md`](volumes.md). Omit for stateless apps or to keep a plain bind mount.
- `create_dirs`: subdirectories created under `{{ compose_deploy_dir }}/<app>/` before the stack starts — only needed for content that stays a bind mount.
- `configs`: templates to render. Defaults to `force: true` (overwrite on drift); add `force: false` only if the app writes back to the same file itself (see `dashy`'s entry). Set `no_log: true` if a config renders a real secret, or `--diff` prints it in plaintext (see [`secrets.md`](secrets.md)). Secrets this repo can generate go in `secrets_registry.yaml`, not a raw `lookup('password', ...)` in the template.
- `scripts`: helper scripts copied verbatim into `<app>/scripts/`.
- `caddy`: omit for apps with no HTTP frontend. Each key (`default`, or a name per route — see `shlink`'s `short`/`web` pattern) needs an `upstream` (`container:port`) and optionally `auth: false` to skip Tinyauth forward-auth.

## 3. Add it to a host's `compose_apps`

In the relevant `ansible/inventory/host_vars/<host>.yaml`, add a minimal entry with just the app name, plus a `caddy` block supplying the hostname if it's routable:

```yaml
compose_apps:
  - name: my-app
    caddy:
      default:
        host: my-app
```

At deploy time this merges with the `app_registry` entry
(`registry_defaults | combine(item, recursive=True)`). If the host is in
`app_hosts` (every managed host), a CNAME for `my-app.{{ caddy_domain }}`
is generated automatically. See [`host-vars.md`](host-vars.md) for the
full field reference, including the alias-variable pattern
(`cobalt_host`, `lldap_host`, ...) for apps whose own config needs to
know their routed hostname.

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
