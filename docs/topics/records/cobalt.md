# Cobalt: Service Record

A media-download proxy on `services`. The catalog's facts are in the [coverage table](../disaster-recovery/coverage.md); there is no other topic doc for it.

## Dependencies

- Needs the `caddy-proxy` network, its route and a `.env` holding `COBALT_API_URL`. It has no volume or secret.
- Needed by nothing.

## Data

- It stores nothing: no volume, and its root filesystem is read-only. Cookie support for authenticated downloads is off in the compose file, so it holds no third-party credential.

## Exposure

- Its Caddy route sets `auth: false`, so Tinyauth does not gate it ([`caddy.md`](../services/caddy.md)). Unknown: why it opts out; check the compose file and the commit that added the route.
- Outbound, it fetches whatever address a request names. It drops every capability and exposes port 9000 to Caddy only.

## Threat model

- With no authentication, anyone who can reach the host name can make the server fetch third-party content, which is an abuse and a request-forgery risk. Unknown: whether the route is reachable beyond the tailnet; check the Caddy and DNS exposure and [`tailnet-policy.md`](../infra/tailnet-policy.md).
- Unknown: whether the container can reach internal addresses. Check its network membership on `caddy-proxy`, where it can see other containers.

## Observability

- The container health check requests `/api/serverInfo`, and Beszel reports its state ([`beszel.md`](../monitoring/beszel.md)). Nothing alerts on misuse.

## Disaster recovery

Nothing to back up; recovery tier 3. A deploy rebuilds it.

## Lifecycle

- Upgrade: bump the pinned image tag, which follows major version 11, and deploy.
- Removal: delete its catalog entry and run `cleanup.yaml` ([`cleanup.md`](../deploy/cleanup.md)).
- Waits on nothing.
