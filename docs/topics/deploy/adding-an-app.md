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

- `compose.yaml` is rendered through Ansible's `template` module and written
  to `{{ compose_deploy_dir }}/<app>/` on the target host, the same way as
  `configs/`. It can reference an Ansible variable directly
  (`TZ: "{{ server_timezone }}"`) for anything **non-secret and domain-free**.
  Name the file `compose.yaml.j2` when it does; the suffix is stripped at
  deploy time, so it still lands as `compose.yaml`, and it marks in the repo
  which apps template their compose file. See `kms` or `bind9`.

  Every app's `compose.yaml` is deployed in one shared loop at
  `mode: "0644"`, world-readable, with no per-app `no_log:`. So what goes
  where:

  | Value | Goes in | Why |
  | :--- | :--- | :--- |
  | Non-secret, domain-free (timezone, a port) | `compose.yaml.j2` | Safe in a world-readable file. |
  | A real secret (API key, password, token) | `configs/*.j2` with `no_log: true` | `configs` supports `no_log:` and a `mode`. |
  | Anything built from `main_domain`, `lan_domain` or `caddy_domain` (a routed URL, an LDAP base DN, a DNS name list) | `configs/*.j2` with `no_log: true` | The domain is not a credential, but it is identifying and should not sit in a world-readable file. `secret_catalog.yaml` routes `main-domain` through the same cached, gitignored mechanism as every other secret ([`secrets.md`](../secrets/secrets.md)). See `cobalt`, `shlink`, `lldap` and `step-ca`'s `env.j2`. |

  Before inlining a value, trace what it is built from: if any of it comes
  from `main_domain`, it goes in `configs/*.j2`.
- Anything in `configs/` is rendered through Ansible's `template` module
  (so it can reference any Ansible variable, e.g. `{{ server_timezone }}`)
  and written to whatever `dest` its `app_catalog` entry specifies —
  this is also how `.env` files are generated, for apps that either need
  `env_file:` to inject a whole set of container-facing vars at once, or
  where the value is a real secret and needs `configs`' `no_log:`/`mode`
  handling regardless of whether it's a single value.

### Container hardening

Every service sets `cap_drop: [ALL]` and `security_opt: [no-new-privileges:true]`,
then adds back only what its process does. How to choose, what each capability
is for, and how to verify a set is in
[`container-hardening.md`](container-hardening.md). Before adding the pair to a
new app, scan its image: `python -m container_hardening.scan_image IMAGE`, run
from `tools/`, lists the setuid files, file capabilities and shell-script
privilege helpers it carries
([`scan_image.py`](../../../tools/container_hardening/scan_image.py)).

Search for `no-new-privileges` under `docker/` to see which services have the
pair today. What each one keeps, and why:

| App | Keeps | Why |
| :--- | :--- | :--- |
| `beszel-hub` | Nothing | Root, reading and writing only files its own root-owned volume holds. |
| `beszel-agent` | Nothing | Root on the host network. |
| `dashy` | Nothing | Its image gives `ping` `cap_net_raw`, but only an ICMP ping check runs it. The HTTP status checks configured here do not, and a ping check added to its config would stop working. |
| `gatus` | Nothing | Non-root (uid 10001) with no file capabilities. No ICMP check is configured; one would need `NET_RAW`. |
| `bluemap` | `DAC_OVERRIDE` | Creates files in a directory another user owns. |
| `tinyauth` | `DAC_OVERRIDE` | Root over a `/data` the volume seed leaves owned by another user. SQLite must create its journal beside `tinyauth.db`; without the capability the session insert at login fails with a read-only database error. |
| `backup-agent` | `DAC_READ_SEARCH` | Root, only reading files other users own (schedule files belong to the deploy user, each volume to its app's user). Without it the container stays healthy but cannot open what it archives. |
| `caddy` | `NET_BIND_SERVICE` | The base image sets `cap_net_bind_service` on the binary and the process runs as root. |
| `step-ca` | `NET_BIND_SERVICE` | The binary carries the capability with the effective bit set, so the kernel refuses the `exec` without it (`capabilities(7)`, "Safety checking for capability-dumb binaries"). |
| `lldap` | `CHOWN`, `SETUID`, `SETGID`, `DAC_OVERRIDE` | The entrypoint chowns `/data`, drops to another user, and writes to `/data` as a check. |
| `seaweedfs`, `minecraft` server and backup services | `CHOWN`, `SETUID`, `SETGID` | The entrypoint starts as root to chown a volume, then drops to another user. |
| `librespeed` | `CHOWN`, `SETUID`, `SETGID`, `DAC_OVERRIDE`, `FOWNER` | As above, and the entrypoint deletes and re-copies its web root on every start, whose files belong to `www-data` in a sticky directory after the first start. |
| `openbao` | `IPC_LOCK` | Non-root; `mlock` only. |
| `docker-socket-proxy` sidecars (`beszel-agent`'s `dockerproxy`, `backup-agent`'s `backup-dockerproxy`) | Nothing | Root, as the image sets `USER root` and HAProxy does not drop to another user. It binds port 2375, above the privileged range, and connects to a Docker socket that root owns, so it needs no capability to reach it. |
| `minecraft` `restore-backup` | `DAC_OVERRIDE`, `CHOWN`, `FOWNER` | Root: `run_restore.sh` deletes everything in `/data` (owned by uid 1000), then `tar` restores each file's owner and mode. Runs with `network_mode: none`. |
| `test-upgrade` dry run | Nothing | Starts as uid 1000 instead of letting the image switch to it. |

### Helper containers

A container Ansible or systemd starts for one job gets the same pair, no
network unless it calls a service, and only what the job does as root. Where
the job writes only into the volumes it is given, it also runs with
`read_only: true`.

| Helper | Keeps | Network | Why |
| :--- | :--- | :--- | :--- |
| Volume seed (`seed_volume.yaml`), restore role (both containers) | `CHOWN`, `FOWNER`, `DAC_OVERRIDE`, `FSETID` | None | `cp -a` and `tar` keep each file's owner and mode and write over other users' files. Without `FSETID`, `chmod` drops a setgid bit and the job still exits 0. |
| `volume-file-rm.yaml` | `DAC_OVERRIDE` | None | Deletes inside directories another user owns. |
| OpenBao data `chown` | `CHOWN`, `DAC_OVERRIDE` | None | Lists directories the previous owner left at `0700`. It does not take `DAC_READ_SEARCH`, which Docker's default set lacks and which allows `open_by_handle_at`. The user-id lookup before it needs nothing. |
| step-ca cert helpers (`cert-renewer@.service`, `step_ca_cert` tasks): `needs-renewal`, renew, `inspect`, issue | `DAC_OVERRIDE` | Renew and issue only | `step` writes the files at `0600` and the chown hands them to the app's own user, so reading and rewriting them takes the capability. A failed `inspect` read is taken for "no certificate" and reissues over a valid one. |
| step-ca cert helpers: the two `chown` containers | `CHOWN` | None | Hands the files to the app's user. |
| `cloud-sync` unit | `DAC_OVERRIDE` | Yes (S3) | `rclone.conf` is `0600` and owned by the deploy user. |
| `check-freshness` listing | Nothing | Yes (S3) | Mounts nothing; read-only root and a non-root user. |
| `lldap_bootstrap` (three containers) | Nothing | Yes (lldap API) | Read-only root, plus a `tmpfs` at `/tmp` for the one that runs `bootstrap.sh`. |

### What CI covers

CI boot-tests every changed app that is not excluded, which catches a container
that no longer starts or stays healthy; see
[`gates.md`](../engineering/ci/gates.md#compose-boot-test) for which apps it
skips. It does not exercise what an app does once running, or when its
container restarts: an entrypoint that cleans up after its previous start
fails only on the second one, so restart the container once when you add
capabilities to an app like that.

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
| `routes` | Omit for apps with no HTTP frontend. Each key (`default`, or a name per route — see `shlink`'s `short`/`web` pattern) needs an `upstream` (`container:port`) and optionally `auth: false` to skip Tinyauth forward-auth, and `read_only: true` to answer every method but `GET` and `HEAD` with 405 (after the auth check, so an unauthenticated request still gets the auth response). |
| `backup` | Omit for an app with nothing to back up. `volumes` (required) lists the volumes to back up, each declared in `volumes`. The other keys are optional and fall back to `backup_defaults` in `group_vars/all/main.yaml`; see [`backup` keys](#backup-keys). |

The `check-app-catalog` pre-commit hook rejects a repeated app name, a route with no `upstream`, a `backup` block that names no volume or one its `volumes` doesn't declare, a backup setting of the wrong shape or a key that isn't one (here, in a host's own `backup:` override, or in `backup_defaults`), a cloud target `storage` doesn't define, and a host that would start backing up without its SeaweedFS secret pair and host variables. See [`ci/gates.md`](../engineering/ci/gates.md#app-catalog-rules).

### `backup` keys

| Key | Meaning |
| :--- | :--- |
| `cron` | Schedule; default from `backup_defaults`. |
| `retention_days` | How long backups are kept; default from `backup_defaults`. |
| `compression` | `gz`, `zst` or `none`. Use `none` when the source is already compressed. |
| `stop_during_backup` | Stops the app's container while its volume is archived. Also needs the matching compose label; see [`backup.md`](../disaster-recovery/backup.md). |
| `cloud_targets` | The clouds `cloud_sync` also relays the backup to. A list replaces the default list rather than adding to it, and each name must be a key of `cloud_sync_targets` on `storage`. |

A host that gains its first backed-up app also needs its own SeaweedFS
secrets; see [`deployment-flow.md`](deployment-flow.md).

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
