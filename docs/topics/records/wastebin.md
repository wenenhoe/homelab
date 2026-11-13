# Wastebin: Service Record

A paste service on `services`. The image build is in [`wastebin.md`](../services/wastebin.md); the catalog's facts are in the [coverage table](../disaster-recovery/coverage.md).

## Dependencies

- Needs the `caddy-proxy` network, its route and the `data` volume, which holds its SQLite database. The image is built in this repository from the upstream image, and the host pulls it from the registry. Needed by nothing.

## Data

- Pasted text in the SQLite database in `data`. Pastes can hold secrets that people paste in; the service does not know.

## Exposure

- Reached through Caddy behind Tinyauth. The container runs as `10001:10001`, drops every capability and exposes port 8088 to Caddy only.

## Threat model

- Anyone with a Tinyauth login can read the pastes whose address they know. Pastes are not scanned for secrets.
- The image adds a static `wget` for the health check and an empty data directory ([`wastebin.md`](../services/wastebin.md)); nothing else differs from upstream.

## Observability

- The container health check and Beszel report its state ([`beszel.md`](../monitoring/beszel.md)); the archive is covered by the host's backup heartbeat ([`gatus.md`](../monitoring/gatus.md)).

## Disaster recovery

Backed up: `data` at the default schedule ([`backup.md`](../disaster-recovery/backup.md)). Acceptable loss and downtime: Unknown; check [`exercises.md`](../disaster-recovery/exercises.md).

## Lifecycle

- Upgrade: bump the Wastebin version in the Dockerfile and compose tag, let the workflow build the image, then deploy ([`wastebin.md`](../services/wastebin.md)).
- Removal: delete its catalog entry and run `cleanup.yaml` ([`cleanup.md`](../deploy/cleanup.md)); the data goes with the volume.
- A volume populated before the container user was set needs a one-time `chown` ([`wastebin.md`](../services/wastebin.md)).
