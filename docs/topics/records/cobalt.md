# Cobalt: Service Record

A media-download proxy on `services`. The catalog's facts are in the [coverage table](https://wenenhoe.github.io/homelab/dr-coverage/); there is no other topic doc for it.

## Dependencies

- Needs the `caddy-proxy` network, its route and a `.env` holding `COBALT_API_URL`. It has no volume or secret.
- Needed by nothing.

## Data

- It stores nothing: no volume, and its root filesystem is read-only. Cookie support for authenticated downloads is off in the compose file, so it holds no third-party credential.

## Exposure

- Its Caddy route sets `auth: false`, so Tinyauth does not gate it ([`caddy.md`](../services/caddy.md)). It is a public API endpoint: clients call it directly with no browser session, so Tinyauth cannot gate it, as the catalog entry's comment says.
- Outbound, it fetches whatever address a request names. It drops every capability and exposes port 9000 to Caddy only.

## Threat model

- With no authentication, anyone who can reach the host name can make the server fetch third-party content, which is an abuse and a request-forgery risk. Unknown: whether the route is reachable beyond the tailnet; check the Caddy and DNS exposure and [`tailnet-policy.md`](../infra/tailnet-policy.md).
- The container is on `caddy-proxy`, the network every proxied app shares, so it can reach the other containers' ports on it. Unknown: whether it can reach other internal addresses; check the host's Docker network and the gateway's rules.

## Observability

- The container health check requests `/api/serverInfo`, and Beszel reports its state ([`beszel.md`](../monitoring/beszel.md)). Nothing alerts on misuse.

## Disaster recovery

Nothing to back up; recovery tier 3. A deploy rebuilds it.

## Lifecycle

- Upgrade: bump the pinned image tag, which follows major version 11, and deploy.
- Removal: delete its catalog entry and run `cleanup.yaml` ([`cleanup.md`](../deploy/cleanup.md)).
- Waits on nothing.
