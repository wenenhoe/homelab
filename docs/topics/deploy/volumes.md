# Named Volumes: Storage Architecture

Persistent app data lives in Docker-managed named volumes, not bind
mounts — see [ADR 0005 (Persistent container state)](../../decisions/0005-persistent-container-state-and-host-permissions/revision-000.md)
for why. An app's stack directory under `compose_deploy_dir` still holds
its `compose.yaml` and rendered `.env`/scripts, but real state (databases,
caches, certs, world saves) lives in a volume Docker owns, created and
populated by Ansible rather than a `./data`-style host path.

## Declaring volumes

A `volumes` list in an app's `app_catalog` entry triggers this. An app
with no `volumes` key is unaffected (see
[Backward compatibility](#backward-compatibility-with-bind-mounted-apps)):

```yaml
app_catalog:
  dashy:
    volumes:
      - name: data
    configs:
      - src: conf.yaml.j2
        dest: "data/conf.yml"
```

Each entry becomes a Docker volume named `<app>_<name>` (see `ensure_volume.yaml`), referenced in `compose.yaml` as an `external: true` volume so Ansible — not `docker compose` — owns its lifecycle:

```yaml
services:
  dashy:
    volumes:
      - data:/data
volumes:
  data:
    external: true
    name: dashy_data
```

## Volume creation (`ensure_volume.yaml`)

For each declared volume, `roles/compose/tasks/ensure_volume.yaml` creates
the volume on every deploy (`community.docker.docker_volume`,
`state: present`), labelled `homelab.app`/`homelab.volume`. The labels let
`cleanup.yaml` find and remove it later even after the `app_catalog` entry is
gone; see [`cleanup.md`](cleanup.md). A new app starts with an empty volume.

## Ansible-managed content: staging and seeding

Some volumes need to hold files Ansible generates — rendered configs,
static scripts — not just app-written data. Ansible can't write directly
into a volume's mount target, so anything whose `configs`/`scripts` `dest`
matches a declared volume name is rendered to a staging path
(`<app>/_staging/<volume>/...`) and copied in only when it changes:

```yaml
configs:
  - src: conf.yaml
    dest: data/conf.yaml    # "data" matches a declared volume -> staged + seeded
  - src: env.j2
    dest: .env               # no volume named ".env" -> deployed directly, as always
```

The `app_deploy_plan` filter classifies each item once per app (`compose_app_deploy_plan`):

| | Direct | Seeded |
| :--- | :--- | :--- |
| Which items | `dest` names no declared volume; a script when the app has no `scripts` volume | `dest` is inside a declared volume; a script when it has one |
| Written to | the final path | `<app>/_staging/<volume>/` |
| Change detection | by the task that writes it | checksum diff against the last staged copy |
| Reaches the stack | as written | `seed_volume.yaml` copies the changed volume in (`cp -a /src/. /dest/`) and flags `compose_app_extra_changed`, so the stack restarts only on a change |

A `dest` naming a volume with nothing inside it (`data`, not `data/<file>`) fails the run, naming the app and volume. The copy only adds or overwrites staged files, so an app's own runtime data in the volume is left alone.

## Self-managed apps (`bind9`, `caddy`)

`bind9` and `caddy` deploy themselves outside the generic `compose_app`
batch role, each with its own pre-existing config-change detection
(`bind9`'s serial-stripped zone diffing, `caddy`'s plain template
`register`). Both point their rendering at a staging path
(`bind9_config_dir` → `_staging/config`; Caddyfile →
`_staging/caddyfile/Caddyfile`) and reuse `seed_volume.yaml` directly
(`include_role: {name: compose, tasks_from: seed_volume}`), gated on
their own change flag.

## Single-file and subdirectory mounts

A few mounts are a single file or a subdirectory of a volume, not the whole volume — Docker Compose's `volume.subpath` long syntax handles this:

```yaml
volumes:
  - type: volume
    source: caddyfile
    target: /etc/caddy/Caddyfile
    volume:
      subpath: Caddyfile        # caddy's Caddyfile, single file at the volume's root
```

`minecraft`'s `bluemap` service uses the same mechanism to mount just the
`world` subdirectory out of the shared `data` volume it otherwise doesn't
own, and `seaweedfs` mounts its rendered `s3-identity.json` the same way,
out of its own `data` volume. Needs Docker Engine 25+/Compose CLI v2.22+
for subpath support.

## Files mounted read-only from the stack directory

A file or directory that Ansible renders or copies into the stack directory, that the container only reads and that nothing in the container writes beside, can be bind-mounted `:ro` from there instead of seeded into a volume ([ADR 0087 (Ansible-rendered files in containers)](../../decisions/0087-delivering-files-ansible-renders-to-a-container/revision-000.md)). The mount is outside every volume, and a mounted secret keeps `no_log` and a mode that excludes other users, set in its catalog entry like any direct config.

A running container keeps the old content of a file that Ansible replaced, because `template` and `copy` rename a new file over it, and Compose does not notice a changed bind-mounted file. The deploy tasks therefore recreate the service that mounts it:

- Before any Compose call, under whichever tag selection reaches it, `deploy.yaml` reads the deployed `compose.yaml` and finds each service's read-only bind mounts whose source is inside the stack directory, in short and long syntax ([`compose_mounts.py`](../../../ansible/filter_plugins/compose_mounts.py)). Named volumes, writable binds, the Docker socket and any other host path are not counted.
- It writes `compose.override.yaml` in the stack directory, which Compose reads from the project directory without being named. It gives each such service a `homelab.mounted-files-sha256` label: a checksum of the mounted files as they are on the host, with a missing path counted as its own state.
- A changed label recreates that service in the same run and no other. The label is derived from the files and not from a task's `changed` result, so the run after one that failed between writing a file and deploying recreates it too.
- An app with no such mount gets no override file, and one left from before is removed.
- The label is readable by anything with access to the Docker API, so a file that holds a secret is mounted this way only when every secret in it is a generated random value.

A mounted file must exist before its container first starts, or Docker creates a directory at that path: the file is written by `init.yaml`, before the stack comes up. Files seeded into a volume keep the `compose_app_extra_changed` restart, and a directory where the app writes beside a file Ansible placed stays a volume.

## What stays a bind mount

- **Host system resources** — the Docker socket (`backup_agent`/`beszel-agent`'s
  `dockerproxy` sidecars).
- **Anything not declared as a volume.**
- **Files mounted read-only from the stack directory**, as above.

## Backward compatibility with bind-mounted apps

An app with no `volumes` key is unaffected: `ensure_volume.yaml` runs zero
times, no config/script `dest` can match a volume name so everything
routes to `direct`, and staging/seed tasks loop over empty lists. A new
experimental stack using plain `./data:/data` bind mounts and
`create_dirs` deploys exactly as before — named volumes are opt-in per app.

## Cleanup

See [`cleanup.md`](cleanup.md) for how orphaned apps' volumes — and stale volumes on apps that are still deployed — get discovered (by the `homelab.app` label) and removed. For deleting a single file inside a volume that's staying in place, see [`volume-maintenance.md`](volume-maintenance.md) instead.
