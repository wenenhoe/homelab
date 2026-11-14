# BIND9: Service Record

The authoritative, non-recursive internal DNS: a primary on `services` and a secondary on `storage`. How zones are gathered, transferred and rendered is in [`bind9.md`](../services/bind9.md); the catalog's facts are in the [coverage table](../disaster-recovery/coverage.md).

## Dependencies

- Needs the host's published port 53 (TCP and UDP), the `config`, `cache`, `records` and `run` volumes, and the `dns_zones` of every app host from `host_vars`.
- The secondary also needs the `dns-transfer-key` secret and the primary's address to transfer zones.
- Needed by every host and service that resolves an internal name, through the gateway's resolver, which forwards the internal zones to both servers ([`bind9.md`](../services/bind9.md#losing-a-server)).

## Data

- Zone files rendered from inventory; the secondary keeps what it has transferred in `records`. None of it is secret.
- The transfer key is a secret, rendered `0640` for the `bind` user with logging suppressed.

## Exposure

- Port 53 is published on every interface of each host. The server is authoritative only, so it does not recurse for clients ([`bind9.md`](../services/bind9.md)).
- Zone transfers are signed with the transfer key, and the primary allows no other transfer. The NOTIFY that triggers one is unsigned.
- It has no Caddy route and runs as the `bind` user with every capability dropped.
- Unknown: which networks can reach port 53. Check the host firewalls and the gateway rules in [`network-infra.md`](../infra/network-infra.md).

## Threat model

- A forged or altered record redirects a service name. Records come only from the repository, and transfer is keyed.
- A DNS outage stops name resolution. Either server answers every query alone, so losing one leaves names resolving ([`bind9.md`](../services/bind9.md#losing-a-server)).
- A secondary that cannot refresh stops answering for a zone after one week.
- Unknown: whether the unsigned NOTIFY could be abused to force transfers. Check the BIND log for refused notifies.

## Observability

- The container health check runs `pebble health`, and Beszel reports the container state ([`beszel.md`](../monitoring/beszel.md)).
- Unknown: whether anything checks that a name actually resolves. Check Gatus for a DNS probe; its documented endpoints are heartbeats only ([`gatus.md`](../monitoring/gatus.md)).

## Disaster recovery

Not backed up; recovery tier 3. The zones are derived from the repository, so redeploying the role rebuilds them, and the secondary refills by transfer. A secondary that has never transferred answers `SERVFAIL` for its zones until the primary is reachable ([`bind9.md`](../services/bind9.md#a-secondary)). It holds no data a restore would bring back. Acceptable loss and downtime: Unknown; check [`exercises.md`](../disaster-recovery/exercises.md).

## Lifecycle

- Upgrade: bump the pinned image in the compose template and deploy; the role merges its Docker daemon settings with the `docker` role ([`docker-daemon.md`](../deploy/docker-daemon.md)).
- Removal: removes name resolution for the lab. Remove the secondary before the primary.
- Waits on the `docker` role for the shared daemon file. The primary renders zones before the secondary pulls them ([`bind9.md`](../services/bind9.md#self-managed-deploy-ordering)).
