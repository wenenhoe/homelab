# Named Volumes: Storage Architecture

Persistent app data lives in Docker-managed named volumes, not bind mounts. An app's stack directory under `compose_deploy_dir` still holds its `compose.yaml` and any rendered `.env`/scripts, but real state (databases, caches, certs, world saves...) lives in a volume Docker owns, created and populated by Ansible rather than existing as a `./data`-style host path.

## Declaring volumes

A `volumes` list in an app's `app_registry` entry is what triggers all of this — an app with no `volumes` key behaves exactly as it did before this existed (see [Backward compatibility](#backward-compatibility-with-bind-mounted-apps) below):

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

For each declared volume, `roles/compose/tasks/ensure_volume.yaml` runs once per deploy:

1. Create the volume (`community.docker.docker_volume`, `state: present`), labelled `homelab.app`/`homelab.volume` — this label is what lets `cleanup.yaml` find and remove an app's volumes later even after its `app_registry` entry (and therefore its declared `volumes` list) is gone. See [`cleanup.md`](cleanup.md).
2. Check whether a legacy bind-mount directory still exists at the expected path (`legacy_path`, defaulting to the volume's own name).
3. If it does, copy its contents into the new volume once via a throwaway `alpine` container, then rename the old directory to `<path>.migrated` — its absence on the next run is the only idempotency check needed, no separate marker file.

This only ever runs against real on-disk data; a fresh app with nothing at the legacy path just gets an empty volume.

## Ansible-managed content: staging and seeding

Some volumes need to hold files Ansible generates — rendered configs, static scripts — not just data the app writes itself. Ansible can't write directly into a volume's mount target, so anything whose `configs`/`scripts` `dest` matches a declared volume name is instead rendered to a staging path (`<app>/_staging/<volume>/...`) and copied into the volume only when it actually changes:

```yaml
configs:
  - src: conf.yaml
    dest: data/conf.yaml    # "data" matches a declared volume -> staged + seeded
  - src: env.j2
    dest: .env               # no volume named ".env" -> deployed directly, as always
```

This classification happens once per app in `init.yaml`'s `compose_app_deploy_plan` fact (`configs`/`scripts`, each split into `direct`/`seeded`), then:

- **Direct** items deploy straight to their final path — identical to pre-volumes behavior.
- **Seeded** items render/copy to staging. Ansible's own `template`/`copy` idempotency (a checksum diff against the previous staging file) is what decides whether anything changed — no bespoke diffing needed for the common case.
- Any volume with at least one changed staged file gets bulk-copied from staging into the volume (`seed_volume.yaml`: one throwaway container, `cp -a /src/. /dest/`) and that change feeds `compose_app_extra_changed`, so the stack restarts when its config actually changed, not just because a template happened to run.

Because the bulk copy only ever adds/overwrites what's in the staging tree, anything else already in the volume — app-generated state living alongside a seeded file, like an app's own runtime database sitting next to its rendered config — is left untouched.

## Self-managed apps (`bind9`, `caddy`)

`bind9` and `caddy` deploy themselves directly rather than through the generic `compose_app` batch role, and each already had its own bespoke config-change detection before volumes existed (`bind9`'s serial-stripped zone diffing, `caddy`'s plain template `register`). Rather than duplicate the staging/seed mechanism, both roles:

1. Point their own rendering at a staging path (`bind9_config_dir` -> `_staging/config`; `caddy`'s Caddyfile -> `_staging/caddyfile/Caddyfile`) instead of the old bind-mount path.
2. Reuse `seed_volume.yaml` directly via `include_role: {name: compose, tasks_from: seed_volume}`, gated on their own already-computed change flag (`bind9_dns_changed`, `caddy_config_changes.changed`).

No change to their existing diffing logic was needed — it was already comparing against "the previous rendition," which is exactly what a staging path is.

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

`minecraft`'s `bluemap` service uses the same mechanism to mount just the `world` subdirectory out of the shared `data` volume it otherwise doesn't own. This needs a reasonably recent Docker Engine/Compose (subpath support landed in the Compose Spec in 2023 — Engine 25+, Compose CLI v2.22+ roughly).

## What stays a bind mount

Two categories are deliberately never converted:

- **Host system resources** — the Docker socket (`lldap`/`diun`/`beszel-agent`'s `dockerproxy` sidecars, `dockge`), and `dockge`'s `/opt/stacks` (it needs to see the real host directory tree of every stack's compose files, not an isolated volume).
- **Anything not declared as a volume** — see below.

## Backward compatibility with bind-mounted apps

An app with no `volumes` key in its registry entry is completely unaffected by any of this. Every place `compose_app_item.volumes` is read defaults to an empty list, which means:

- `ensure_volume.yaml`'s loop runs zero times.
- The classify step's `volume_names` list is empty, so no config or script `dest` can ever match one — everything routes to `direct`, deployed exactly as before.
- The staging/seed tasks all loop over empty lists — no-ops.

A new experimental stack using plain `./data:/data`-style bind mounts and `create_dirs` deploys exactly as it always did; adopting named volumes is purely opt-in per app.

## Cleanup

See [`cleanup.md`](cleanup.md) for how orphaned apps' volumes get discovered (by the `homelab.app` label, since the registry entry is gone by the time an app is orphaned) and removed under the same keep/delete policy as their stack directory.
