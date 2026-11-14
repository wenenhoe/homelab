# BentoPDF: Service Record

A self-hosted PDF toolbox on `services`. The catalog's facts are in the [coverage table](../disaster-recovery/coverage.md); there is no other topic doc for it.

## Dependencies

- Needs the `caddy-proxy` network and its Caddy route. It has no volume, secret or database.
- Needed by nothing.

## Data

- It stores nothing on the host: the catalog declares no volume. Unknown: whether documents a user opens are processed in the browser or uploaded to the container; check the image's documentation.

## Exposure

- Reached through Caddy behind Tinyauth. The container exposes port 8080 to the `caddy-proxy` network only and drops every capability.
- Unknown: whether the image makes outbound calls; check its network traffic.

## Threat model

- Uploaded documents may be sensitive and a malformed PDF may exploit the converter. The route is behind Tinyauth and the container has no volume to write to. Unknown: whether the root filesystem is read-only; check the compose file.

## Observability

- Its container health state is reported by Beszel ([`beszel.md`](../monitoring/beszel.md)). Nothing else watches it, and nothing depends on it.

## Disaster recovery

Nothing to back up; recovery tier 3. A deploy rebuilds it ([`exercises.md`](../disaster-recovery/exercises.md)).

## Lifecycle

- Upgrade: bump the pinned image tag and deploy.
- Removal: delete its catalog entry and run `cleanup.yaml` ([`cleanup.md`](../deploy/cleanup.md)).
- Waits on nothing.
