# Adding an App

New apps are wired in through three places: a `docker/<app>/` directory, an `app_registry` entry, and a `compose_apps` entry on whichever host(s) should run it.

## 1. Add `docker/<app>/`

Create a directory holding the app's Compose stack:

```
docker/<app>/
├── compose.yaml           # Required — or compose.yaml.j2, see below
└── configs/               # Optional — Jinja2 templates rendered onto the host
    └── env.j2
```

- `compose.yaml` is rendered through Ansible's `template` module and
  written to `{{ compose_deploy_dir }}/<app>/` on the target host — same
  mechanism as `configs/`, just always on regardless of whether the file
  actually contains any Jinja2. That means it can reference an Ansible
  var directly (`TZ: "{{ server_timezone }}"`) for anything
  **non-secret and domain-free**. Name the file `compose.yaml.j2` when
  it does this — the `.j2` suffix is stripped back off at deploy time,
  so it still lands as plain `compose.yaml` on the host, but it's a
  visible marker in the repo for which apps actually template their
  compose file. See `kms` or `bind9`'s `compose.yaml.j2` for the
  pattern.

  **Never a real secret, and never anything that leaks the domain.**
  This task copies every app's `compose.yaml` in one shared loop at a
  fixed `mode: "0644"`, world-readable, with no per-app `no_log:`
  support — the opposite of what `configs` gives you (see below). A
  real secret (API key, password, token) still belongs in a
  `configs/*.j2` template with `no_log: true`, never inlined here — and
  so does anything derived from `main_domain`/`lab_domain`/
  `caddy_domain` (a routed URL, an LDAP base DN, a DNS name list — see
  `cobalt`/`shlink`/`lldap`/`step-ca`'s `env.j2` for what stayed there).
  The domain isn't a credential, but it's still the one piece of
  identifying info that shouldn't sit in a world-readable file on the
  host — `main-domain`'s own entry in `secrets_registry.yaml` routes it
  through the same cached/gitignored mechanism as everything else in
  `secrets.md` for that reason. A quick check before inlining anything:
  if the value or anything it's built from ultimately traces back to
  `main_domain`, it goes in `configs/*.j2` with `no_log: true`, not here.
- Anything in `configs/` is rendered through Ansible's `template` module
  (so it can reference any Ansible variable, e.g. `{{ server_timezone }}`)
  and written to whatever `dest` its `app_registry` entry specifies —
  this is also how `.env` files are generated, for apps that either need
  `env_file:` to inject a whole set of container-facing vars at once, or
  where the value is a real secret and needs `configs`' `no_log:`/`mode`
  handling regardless of whether it's a single value.

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
