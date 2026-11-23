# BentoPDF: Service Record

A self-hosted PDF toolbox on `services`. The catalog's facts are in the [coverage table](https://wenenhoe.github.io/homelab/dr-coverage/); there is no other topic doc for it.

## Dependencies

- Needs the `caddy-proxy` network and its Caddy route. It has no volume, secret or database.
- The route is reachable only while three other services are up: the internal DNS that resolves its host name ([`bind9.md`](../services/bind9.md)), Caddy ([`caddy.md`](../services/caddy.md)), and Tinyauth, which Caddy asks about every request because the route does not set `auth: false` ([`caddy.md`](../services/caddy.md#caddyfile-generation)).
- Needed by nothing.

## Data

- It stores nothing on the host: the catalog declares no volume. Unknown: whether documents a user opens are processed in the browser or uploaded to the container; check the image's documentation.

## Exposure

- Reached through Caddy behind Tinyauth. The container exposes port 8080 to the `caddy-proxy` network only and drops every capability.
- Unknown: whether the image makes outbound calls; check its network traffic.

## Threat model

- Uploaded documents may be sensitive and a malformed PDF may exploit the converter. The route is behind Tinyauth and the container has no volume to write to. The root filesystem is writable, since the compose file sets no `read_only`, so a compromised converter can write to the container's own layer until it is recreated.

## Observability

- The container health check marks it unhealthy and Beszel shows that state ([`beszel.md`](../monitoring/beszel.md)). Gatus has no endpoint for it.
- Alerts on the hub are set by hand in its database ([`beszel.md`](../monitoring/beszel.md#alert-notifications)); the repository declares none, so nothing alerts on an unhealthy container. Nothing depends on it.

## Disaster recovery

Nothing to back up; recovery tier 3. A deploy rebuilds it ([`exercises.md`](../disaster-recovery/exercises.md)).

## Lifecycle

- Upgrade: bump the pinned image tag and deploy.
- Removal: delete its catalog entry and run `cleanup.yaml` ([`cleanup.md`](../deploy/cleanup.md)).
- Waits on nothing.
