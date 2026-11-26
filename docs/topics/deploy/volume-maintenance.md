# Volume Maintenance: Resetting Content Inside a Volume

Two ad hoc playbooks for touching content inside a volume that's staying
deployed, without going through `cleanup.yaml`'s whole-volume-of-an-
orphaned-or-stale-app removal (see [`cleanup.md`](cleanup.md) for that):

- **`volume-file-rm.yaml`** — remove specific, named file(s) you list
  yourself. Use when you know exactly which file(s) need to go and the
  volume holds other content you must not touch.
- **`volume-reset.yaml`** — wipe the volume entirely and recreate it,
  restoring only what Ansible seeds into it (rendered configs/scripts —
  see [`volumes.md`](volumes.md)). Use when you want to discard *all*
  app-written runtime state and don't need to enumerate individual files.

Both stop before changing anything unless `--limit` leaves exactly one
managed host (plus `localhost` for the secrets play), because an app such as
`caddy` is declared on every host and a run without `--limit` would touch the
same volume on all of them.

Both reuse the same throwaway-`alpine`-container / `ensure_volume.yaml`
pattern the rest of `compose` role uses — nothing reaches into a
volume's real on-disk mountpoint directly (see
[`volumes.md`](volumes.md)).

## Resetting a volume entirely

For apps whose volume mixes Ansible-seeded config with the app's own
runtime state (e.g. `dashy`'s `conf.yml` living alongside its own cache
in the same volume — see `volumes.md`), a plain "delete the volume"
would also delete the seeded config, and a later `deploy.yaml` run won't
notice and reseed it: the reseed trigger is a checksum diff between the
rendered template and the *last staged copy*, not a check of whether the
volume is actually populated.

`volume-reset.yaml` handles this by deleting the volume, recreating it
empty, then unconditionally re-running the seed step for that volume if
it has any staged content — restoring exactly what Ansible manages and
nothing else:

```sh
ansible-playbook playbooks/volume-reset.yaml --limit services,localhost \
  -e volume_reset_app=dashy -e volume_reset_volume=data \
  -e volume_reset_confirm=true
```

For a volume with no seeded content at all (pure runtime data, e.g. a
db-only volume), this is equivalent to deleting and recreating an empty
volume — there's nothing to restore.

## Choosing between the two

| | `volume-file-rm.yaml` | `volume-reset.yaml` |
| --- | --- | --- |
| You know the exact file(s) to remove | Yes | Not needed |
| Other runtime files in the volume must survive | Yes — only what you list is touched | No — everything not Ansible-seeded is gone |
| Volume mixes seeded config with runtime state | Config untouched either way | Config is restored automatically |

## Why a playbook and not an ad hoc command

Volumes are Ansible-owned objects ([`volumes.md`](volumes.md)), reached only through a throwaway `alpine` container. A named volume that does not exist is created empty by `docker_container` instead of erroring, so the playbook first checks it exists (`docker_volume_info`) and fails on a typo in `volume_rm_app` or `volume_rm_volume`.

## Resetting a SQLite database

Deleting only the `.db` file isn't enough if the app was using
[WAL mode](https://www.sqlite.org/wal.html): uncommitted data can still
be sitting in `-wal`/`-shm` sidecar files, and a fresh `.db` created next
to a leftover `-wal` file can pick up stale data on next start. List all
three explicitly in `volume_rm_paths`:

```sh
ansible-playbook playbooks/volume-file-rm.yaml --limit services,localhost \
  -e volume_rm_app=myapp -e volume_rm_volume=data \
  -e '{"volume_rm_paths": ["app.db", "app.db-wal", "app.db-shm"]}' \
  -e volume_rm_confirm=true
```

The stack is stopped before removal and restarted after by default
(`volume_rm_stop_app`, default `true`) — the app should not have the
database file open while it's deleted out from under it.

## Preview before deleting

```sh
ansible-playbook playbooks/volume-file-rm.yaml --limit services,localhost \
  -e volume_rm_app=myapp -e volume_rm_volume=data \
  -e '{"volume_rm_paths": ["app.db"]}' \
  -e volume_rm_confirm=true --check
```

`docker_compose_v2` and `docker_container` both fully support check
mode, so `--check` previews the stop/remove/restart sequence without
actually running it.
