# LibreSpeed: Service Record

A browser speed test on `services`. The catalog's facts are in the [coverage table](../disaster-recovery/coverage.md); there is no other topic doc for it.

## Dependencies

- Needs the `caddy-proxy` network and its route. It has no volume, secret or database. Needed by nothing.

## Data

- It stores nothing in a volume. Unknown: whether the image keeps test results; check its settings, since the catalog declares no volume.

## Exposure

- Reached through Caddy behind Tinyauth; port 8080 is exposed to Caddy only.
- It keeps `CHOWN`, `DAC_OVERRIDE`, `FOWNER`, `SETGID` and `SETUID` because its entrypoint deletes and recreates its web root on each start ([`adding-an-app.md`](../deploy/adding-an-app.md#container-hardening)).

## Threat model

- A speed test generates bulk traffic for any client that reaches it, which can saturate the link. It is behind Tinyauth, which limits who can do that.
- Unknown: whether the entrypoint's extra capabilities could be narrowed; recheck when the image changes.

## Observability

- Its health state is reported by Beszel ([`beszel.md`](../monitoring/beszel.md)). Nothing else watches it.

## Disaster recovery

Nothing to back up; recovery tier 3. A deploy rebuilds it. No drill has covered it.

## Lifecycle

- Upgrade: bump the pinned image tag and deploy.
- Removal: delete its catalog entry and run `cleanup.yaml` ([`cleanup.md`](../deploy/cleanup.md)).
- Waits on nothing.
