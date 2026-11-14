# Minecraft: Service Record

A Fabric game server with a map viewer and an in-stack backup container, on `play`. The catalog's facts are in the [coverage table](../disaster-recovery/coverage.md); the restore is in [`restore.md`](../disaster-recovery/restore.md).

## Dependencies

- Needs the `caddy-proxy` network for the map route, six volumes (the world in `data`, the backup tars in `backups`, and the map's config, web and data volumes and `extras`), the upgrade and restore scripts, and mod lists that are downloaded from Modrinth at start.
- Needed by nothing else. The `mc-backup` container quiesces the server over RCON, so it needs the server up.

## Data

- The world, player data and mods in `data`; on-host backup tars in `backups`. No credential that this record can name. The RCON port is exposed on the Docker network only. Unknown: how the RCON password is set; check the compose file.

## Exposure

- The game port 25565 is published on every interface of `play`. The map viewer is reached through Caddy behind Tinyauth.
- Outbound, the server downloads mods and server software from the internet at start.
- Each container drops every capability and keeps only what its entrypoint needs; the `restore-backup` helper runs with `network_mode: none` ([`adding-an-app.md`](../deploy/adding-an-app.md#container-hardening)).

## Threat model

- Anyone who can reach port 25565 can try to join. Unknown: whether the server enforces an allow-list or an online-mode check; check the server properties in the compose environment. The network policy treats the only player as a VM ([`tailnet-policy.md`](../infra/tailnet-policy.md)).
- A malicious or broken mod runs inside the server container. Mods come from Modrinth at the version type the compose file selects, which includes betas.
- Unknown: whether a world update pulls a newer game version unattended; the version is set in the compose file.

## Observability

- Container health states are reported by Beszel ([`beszel.md`](../monitoring/beszel.md)), and the backup is covered by the `play` backup heartbeat ([`gatus.md`](../monitoring/gatus.md)). Nothing checks that the world loads.

## Disaster recovery

Backed up: only the `backups` volume, which `mc-backup` fills at 04:00 and the host archives at 04:30; the cloud copy goes to OCI only ([`backup.md`](../disaster-recovery/backup.md), [`cloud-sync.md`](../disaster-recovery/cloud-sync.md)). The restore has two steps: the volume restore, then `restore-minecraft-world.yaml` unpacks the newest tar into `data` ([`restore.md`](../disaster-recovery/restore.md)). Acceptable loss and downtime: Unknown; check [`exercises.md`](../disaster-recovery/exercises.md).

## Lifecycle

- Upgrade: the upgrade script and `compose.upgrade.yaml` run a dry run first (`test-upgrade`); the version is set in the compose file. Unknown: the full procedure; check `docker/minecraft/scripts/run_upgrade.sh`.
- Removal: delete the catalog entry and run `cleanup.yaml`; the world goes with the volumes.
- Waits on the server before the backup and map containers.
