# Named Volumes: Storage Architecture

Persistent app data lives in Docker-managed named volumes, not bind
mounts. An app's stack directory under `compose_deploy_dir` still holds
its `compose.yaml` and rendered `.env`/scripts, but real state (databases,
caches, certs, world saves) lives in a volume Docker owns, created and
populated by Ansible rather than a `./data`-style host path.

## Declaring volumes

A `volumes` list in an app's `app_registry` entry triggers this. An app
with no `volumes` key is unaffected (see
[Backward compatibility](#backward-compatibility-with-bind-mounted-apps)):

```yaml
app_registry:
  dashy:
    volumes:
      - name: data
    configs:
      - src: conf.yaml.j2
        dest: "data/conf.yml"
```

Each entry becomes a Docker volume named `<app>-<name>` (see `ensure_volume.yaml`), referenced in `compose.yaml` as an `external: true` volume so Ansible — not `docker compose` — owns its lifecycle:

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

If a volume's on-disk directory name doesn't match its registry name (e.g. `lldap`'s `letsencrypt/conf` mapping to a `letsencrypt_conf` volume), add `legacy_path`:

```yaml
volumes:
  - name: letsencrypt_conf
    legacy_path: letsencrypt/conf
```

## One-time migration (`ensure_volume.yaml`)

For each declared volume, `roles/compose/tasks/ensure_volume.yaml` runs
once per deploy:

1. Create the volume (`community.docker.docker_volume`, `state: present`),
   labelled `homelab.app`/`homelab.volume` — lets `cleanup.yaml` find and
   remove it later even after the `app_registry` entry is gone. See
   [`cleanup.md`](cleanup.md).
2. Check whether a legacy bind-mount directory still exists at
   `legacy_path` (defaults to the volume's own name).
3. If it does, copy its contents into the volume via a throwaway `alpine`
   container, then rename the old directory to `<path>.migrated` — its
   absence is the idempotency check for the next run.

A fresh app with nothing at the legacy path just gets an empty volume.

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

Classified once per app in `init.yaml`'s `compose_app_deploy_plan` fact
(`configs`/`scripts` split into `direct`/`seeded`):

- **Direct** items deploy straight to their final path, as before.
- **Seeded** items render/copy to staging; Ansible's own checksum diff
  against the previous staging file decides whether anything changed.
- Any volume with a changed staged file gets bulk-copied in
  (`seed_volume.yaml`: throwaway container, `cp -a /src/. /dest/`), which
  feeds `compose_app_extra_changed` so the stack restarts only when its
  config actually changed.

The bulk copy only adds/overwrites what's in the staging tree — anything
else already in the volume (e.g. an app's own runtime database next to
its rendered config) is left untouched.

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

## What stays a bind mount

- **Host system resources** — the Docker socket (`lldap`/`diun`/`beszel-agent`'s
  `dockerproxy` sidecars, `dockge`), and `dockge`'s `/opt/stacks` (needs
  the real host directory tree of every stack's compose files).
- **Anything not declared as a volume.**

## Backward compatibility with bind-mounted apps

An app with no `volumes` key is unaffected: `ensure_volume.yaml` runs zero
times, no config/script `dest` can match a volume name so everything
routes to `direct`, and staging/seed tasks loop over empty lists. A new
experimental stack using plain `./data:/data` bind mounts and
`create_dirs` deploys exactly as before — named volumes are opt-in per app.

## Cleanup

See [`cleanup.md`](cleanup.md) for how orphaned apps' volumes get discovered (by the `homelab.app` label, since the registry entry is gone by the time an app is orphaned) and removed under the same keep/delete policy as their stack directory.
