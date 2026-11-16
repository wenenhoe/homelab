# Wastebin: Service Record

A paste service on `services`. The image build is in [`wastebin.md`](../services/wastebin.md); the catalog's facts are in the [coverage table](../disaster-recovery/coverage.md).

## Dependencies

- Needs the `caddy-proxy` network, its route and the `data` volume, which holds its SQLite database. The image is built in this repository from the upstream image, and the host pulls it from the registry. The deploy creates the volume from the catalog's `volumes` entry, as an external volume named `wastebin_data` ([`volumes.md`](../deploy/volumes.md)). Needed by nothing.

## Data

- Pasted text in the SQLite database in `data`. Pastes can hold secrets that people paste in; the service does not know.

## Exposure

- Reached through Caddy behind Tinyauth, which is the route's only restriction: any logged-in user reaches it. The container runs as `10001:10001`, drops every capability and exposes port 8088 to Caddy only. Its root filesystem is writable, and the compose file limits neither its outbound access nor its network: it shares `caddy-proxy` with every proxied app.

## Threat model

- Anyone with a Tinyauth login can read the pastes whose address they know. Pastes are not scanned for secrets.
- A compromised wastebin can reach the other proxied apps' ports on `caddy-proxy`.
- The image adds a static `wget` for the health check and an empty data directory ([`wastebin.md`](../services/wastebin.md)); nothing else differs from upstream.

## Observability

- The container health check marks it unhealthy and Beszel shows that state ([`beszel.md`](../monitoring/beszel.md)); `restart: always` does not restart an unhealthy container. Gatus has no endpoint for it: the host's backup heartbeat shows that archives land, not that the service is up ([`gatus.md`](../monitoring/gatus.md)).
- Unknown: whether the hub alerts on an unhealthy container. Check the hub's alert rules.

## Disaster recovery

Backed up: `data` at the default schedule, nightly at `30 4 * * *` with seven days of archives kept ([`backup.md`](../disaster-recovery/backup.md)). A restore brings back the newest archive, so up to about a day of pastes can be lost. The container keeps running during the backup, so the archive is a file-level copy of a live SQLite database; `backup.md` makes a corrupt restore the trigger for stopping it. The restore keeps each file's owner and mode from the archive. It is restored per app with the app restore ([`restore.md`](../disaster-recovery/restore.md)) and exercised once a year ([`exercises.md`](../disaster-recovery/exercises.md)). Whether that loss, and how long a restore may take, are acceptable: Unknown.

## Lifecycle

- Upgrade: bump the Wastebin version in the Dockerfile and compose tag, let the workflow build the image, then deploy ([`wastebin.md`](../services/wastebin.md)).
- Removal: delete its catalog entry and run `cleanup.yaml` ([`cleanup.md`](../deploy/cleanup.md)); the data goes with the volume.
- A volume populated before the container user was set needs a one-time `chown` ([`wastebin.md`](../services/wastebin.md)). A restored volume keeps the owner its archive carried.
