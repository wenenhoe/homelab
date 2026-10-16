# Adding an App

New apps are wired in through three places: a `docker/<app>/` directory, an `app_catalog` entry, and a `compose_apps` entry on whichever host(s) should run it.

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
  This task deploys every app's `compose.yaml` in one shared loop at a
  fixed `mode: "0644"`, world-readable, with no per-app `no_log:`
  support — the opposite of what `configs` gives you (see below). A
  real secret (API key, password, token) still belongs in a
  `configs/*.j2` template with `no_log: true`, never inlined here — and
  so does anything derived from `main_domain`/`lab_domain`/
  `caddy_domain` (a routed URL, an LDAP base DN, a DNS name list — see
  `cobalt`/`shlink`/`lldap`/`step-ca`'s `env.j2` for what stayed there).
  The domain isn't a credential, but it's still the one piece of
  identifying info that shouldn't sit in a world-readable file on the
  host — `main-domain`'s own entry in `secret_catalog.yaml` routes it
  through the same cached/gitignored mechanism as everything else in
  `secrets.md` for that reason. A quick check before inlining anything:
  if the value or anything it's built from ultimately traces back to
  `main_domain`, it goes in `configs/*.j2` with `no_log: true`, not here.
- Anything in `configs/` is rendered through Ansible's `template` module
  (so it can reference any Ansible variable, e.g. `{{ server_timezone }}`)
  and written to whatever `dest` its `app_catalog` entry specifies —
  this is also how `.env` files are generated, for apps that either need
  `env_file:` to inject a whole set of container-facing vars at once, or
  where the value is a real secret and needs `configs`' `no_log:`/`mode`
  handling regardless of whether it's a single value.

### Container hardening

A service sets `cap_drop: [ALL]` and `security_opt: [no-new-privileges:true]`
when nothing in it needs a capability. `cap_drop` removes every capability
from the container's bounding set, and `no-new-privileges` stops `exec`
granting any through a setuid binary or a file capability. A process that
runs as a non-root user from its first instruction holds no capability to
begin with, so for it the pair changes nothing unless the image relies on
`exec` granting one. A service that runs as root and only reads and writes
files its own root-owned volume holds (`beszel-hub`, `diun`) loses nothing it
used. One that creates files in a directory another user owns needs
`DAC_OVERRIDE` back (`bluemap`, `tinyauth`). `tinyauth` runs as root over a
`/data` the volume seed leaves owned by another user, and SQLite has to create
its journal file beside `tinyauth.db`; without the capability the session
insert at login fails with a read-only database error.
`beszel-agent` runs as root on the host network and takes the pair too, with
nothing added back; its `dockerproxy` sidecar does not.
`backup-agent` runs as root and only reads, over files other users own (its
schedule files belong to the deploy user, each volume to its app's user), so it
keeps `DAC_READ_SEARCH`, the read-only counterpart of `DAC_OVERRIDE`, and
nothing else. Without it the container stays up and healthy but cannot open
what it archives. Its `backup-dockerproxy` sidecar does not take the pair.
The minecraft `restore-backup` job runs `tar` as root over `/data`, restoring
the owner and mode of every file, so it keeps `CHOWN`, `FOWNER` and
`DAC_OVERRIDE` and runs with `network_mode: none`. `DAC_OVERRIDE` matters when
`/data` was emptied with `rm -rf data/*`, which leaves uid 1000's dotfiles
behind; the script treats that directory as empty and extracts into it.
The `test-upgrade` dry run starts as uid 1000 instead of letting the image switch
to it, so it needs no capability and takes the pair with nothing added back.

The daemon already sets `no-new-privileges` for every container
([`docker-daemon.md`](docker-daemon.md)). The line in each compose file keeps
it on where the service is defined, whatever the daemon is set to, and
`cap_drop` has no daemon-wide default.

Before adding them, read the image's Dockerfile and entrypoint for `setcap`,
`chmod u+s`, `sudo`, `su-exec`, `gosu` and `setpriv`. An image that has any of
these leaves the pair off, adds back what they need, or has the feature that
uses them switched off. Scan the image before adding the pair:
`python -m container_hardening.scan_image IMAGE`, run from `tools/`, lists
its setuid files, file capabilities and shell-script privilege helpers
([`scan_image.py`](../../../tools/container_hardening/scan_image.py)).
It reads the image without running it, so a compiled entrypoint that drops
privileges still needs a boot with the pair set. These images set a file
capability:

- `dashy` gives `ping` `cap_net_raw`, so a non-root user can run it. Only its
  ICMP ping check runs `ping`. The HTTP status checks this repo configures
  do not, so `dashy` takes the pair, and a ping check added to its config
  would stop working.
- `step-ca` gives its `step-ca` binary `cap_net_bind_service` with the
  effective bit set. For such a file the kernel refuses the `exec` outright
  when the process cannot get every capability the file names
  (`capabilities(7)`, "Safety checking for capability-dumb binaries"), so
  after `cap_drop: [ALL]` the container would not start without
  `cap_add: [NET_BIND_SERVICE]`.
- `uptime-kuma` gives `ping` `cap_net_raw` the same way. This repo uses only
  push monitors, so `uptime-kuma` does not keep `NET_RAW`, and a ping monitor
  added in the UI would stop working. It does keep `DAC_OVERRIDE`: the process
  runs as root, and its `kuma.db` files can belong to another user, which root
  can write only with that capability.

Where the capability is one the container is meant to hold, keep it and drop
the rest: Caddy's base image sets `cap_net_bind_service` on its binary and the
process runs as root, so `caddy` sets `cap_add: [NET_BIND_SERVICE]` after
`cap_drop: [ALL]`.

An entrypoint that starts as root to `chown` a volume and then drops to
another user needs `CHOWN`, `SETUID` and `SETGID` back, or to start as that
user. `lldap`, `seaweedfs`, `librespeed` and the `minecraft` server and backup
services take them back with `cap_add`; `lldap` also keeps `DAC_OVERRIDE`,
which its entrypoint's write check on `/data` needs. `openbao` runs as a
non-root user and keeps only `IPC_LOCK`. The `docker-socket-proxy` sidecars
each need their own check of what the process does after it starts.

CI boot-tests every changed app that is not excluded, which catches a container
that no longer starts or stays healthy; see
[`gates.md`](../engineering/ci/gates.md#compose-boot-test) for which apps it
skips. It does not exercise what an app does once running. Search for
`no-new-privileges` under `docker/` to see which services have the pair today.

## 2. Register it in `app_catalog`

In `ansible/inventory/group_vars/all/app_catalog.yaml`, add an entry keyed by the app name. This is the single source of truth for everything about the app that doesn't vary per host:

```yaml
app_catalog:
  my-app:
    volumes:
      - name: data
    configs:
      - src: env.j2
        dest: .env
        mode: "0600"
        no_log: true      # if this .env holds a real secret — see below
    routes:
      default:
        upstream: "my-app:8080"
```

| Field | Purpose |
| :--- | :--- |
| `volumes` | Named Docker volumes Ansible creates (`./data:/data` becomes `data:/data` in the app's `compose.yaml`). See [`volumes.md`](volumes.md). Omit for stateless apps or to keep a plain bind mount. |
| `create_dirs` | Subdirectories created under `{{ compose_deploy_dir }}/<app>/` before the stack starts — only needed for content that stays a bind mount. |
| `configs` | Templates to render. Defaults to `force: true` (overwrite on drift); add `force: false` only if the app writes back to the same file itself — no app in the catalog needs this today, so there's no worked example to point to yet. Set `no_log: true` if a config renders a real secret, or `--diff` prints it in plaintext (see [`secrets.md`](../secrets/secrets.md)). Secrets this repo can generate go in `secret_catalog.yaml`, not a raw `lookup('password', ...)` in the template. |
| `scripts` | Helper scripts copied verbatim into `<app>/scripts/`. |
| `routes` | Omit for apps with no HTTP frontend. Each key (`default`, or a name per route — see `shlink`'s `short`/`web` pattern) needs an `upstream` (`container:port`) and optionally `auth: false` to skip Tinyauth forward-auth. |
| `backup` | Omit for an app with nothing to back up. `volumes` (required) lists the volumes to back up, each one declared in `volumes`. Everything else is optional and falls back to `backup_defaults` in `group_vars/all/main.yaml`: `cron`, `retention_days`, `compression` (`gz`, `zst` or `none`; `none` when the source is already compressed), `stop_during_backup` (stops the app's container while its volume is archived, which also needs the matching compose label — see [`backup.md`](../disaster-recovery/backup.md)), and `cloud_targets` (the clouds `cloud_sync` also relays it to; a list replaces the default list rather than adding to it, and each name must be a key of `cloud_sync_targets` on `storage`). A host that gains its first backed-up app also needs its own SeaweedFS secrets — see [`deployment-flow.md`](deployment-flow.md). |

The `check-app-catalog` pre-commit hook rejects a repeated app name, a route with no `upstream`, a `backup` block that names no volume or one its `volumes` doesn't declare, a backup setting of the wrong shape or a key that isn't one (here, in a host's own `backup:` override, or in `backup_defaults`), a cloud target `storage` doesn't define, and a host that would start backing up without its SeaweedFS secret pair and host variables. See [`ci/gates.md`](../engineering/ci/gates.md#app-catalog-rules).

## 3. Add it to a host's `compose_apps`

In the relevant `ansible/inventory/host_vars/<host>.yaml`, add a minimal entry with just the app name, plus a `routes` block supplying the hostname if it's routable:

```yaml
compose_apps:
  - name: my-app
    routes:
      default:
        host: my-app
```

`resolved_apps` merges this with the `app_catalog` entry (dicts merge, lists
are replaced). If the host is in
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

Some apps front more than one container behind two different hostnames (e.g. `shlink`, which pairs a redirector and a web UI). Give each route its own key under `routes` in both the catalog entry and the host's `compose_apps` entry — the key just needs to match between the two:

```yaml
# app_catalog
shlink:
  routes:
    short:
      upstream: "shlink:8080"
    web:
      upstream: "shlink-web-client:8080"

# host_vars
compose_apps:
  - name: shlink
    routes:
      short:
        host: short
      web:
        host: shlink
```
