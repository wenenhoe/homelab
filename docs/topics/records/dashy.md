# Dashy: Service Record

The service dashboard on `services`. The catalog's facts are in the [coverage table](../disaster-recovery/coverage.md); there is no other topic doc for it.

## Dependencies

- Needs the `caddy-proxy` network, its route and its `data` volume, which is seeded with the rendered `conf.yml` ([`volumes.md`](../deploy/volumes.md)).
- Needed by nothing; it links to the other services and to external consoles.

## Data

- A rendered configuration of links and descriptions, in `data`. It holds no secret. Its status checks make plain HTTP requests only.

## Exposure

- Reached through Caddy behind Tinyauth. The container runs as `1000:1000`, drops every capability and exposes port 8080 to Caddy only.
- Outbound, it makes status-check requests to the linked services. The image's `ping` capability is not kept, so an ICMP check would fail ([`adding-an-app.md`](../deploy/adding-an-app.md#container-hardening)).

## Threat model

- The page lists every service address, which helps an attacker map the lab. It is behind Tinyauth, and the links are not secrets.
- A change to `conf.yml` can point a link anywhere; it is rendered from the repository, which is reviewed.

## Observability

- Its health state is reported by Beszel ([`beszel.md`](../monitoring/beszel.md)). It is itself a view over the other services' status checks.

## Disaster recovery

Not backed up, because the configuration is rendered from the repository; recovery tier 3.

## Lifecycle

- Upgrade: bump the pinned image tag and deploy; the seeded config is overwritten on drift.
- Removal: delete its catalog entry and run `cleanup.yaml` ([`cleanup.md`](../deploy/cleanup.md)).
- Waits on nothing.
