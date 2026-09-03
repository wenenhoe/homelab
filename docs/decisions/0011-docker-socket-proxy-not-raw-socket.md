# 0011. Docker-socket-proxy sidecar, never the raw socket, for anything needing the Docker API

**Status:** Accepted

## Context

Several apps need to talk to the Docker API — `diun` to check running
containers' image tags against registries, `backup_agent` to stop/start
an app around a snapshot, `lldap` (in its original certbot-based
design) to restart itself after a cert renewal. The original `diun`
setup mounted `/var/run/docker.sock` directly, which grants full,
unrestricted control over every container on the host — start, stop,
exec into, delete, mount arbitrary host paths into new containers —
functionally equivalent to root on the host, for a container whose
actual job is read-only image-tag polling.

## Decision

Replace every direct Docker-socket mount with a
`tecnativa/docker-socket-proxy` sidecar, scoped per consumer to only
the specific API capabilities it actually needs (e.g. `diun` gets
`CONTAINERS=1 IMAGES=1` — list containers and images, nothing else;
`backup_agent` additionally needs `POST=1` to stop/start containers
around a snapshot). No app ever mounts the real socket itself.

## Consequences

A compromised `diun` (or any other proxied consumer) can enumerate
containers and images but can't stop, start, exec into, or delete
anything, let alone mount a new host path — a materially smaller blast
radius than raw socket access. This is now the standard pattern for
any future app needing Docker API access in this repo, not a one-off
fix for `diun`.

The trade-off is narrower, not zero: `docker-socket-proxy`'s own grants
have no per-container ACL. `backup_agent`'s `POST=1` grant, for
example, can start/stop *any* container on that host, not just ones
with a matching `stop-during-backup` label — see
[`disaster-recovery.md`](../disaster-recovery.md#whats-backed-up)'s own
noted limitation on this. The label matching that actually scopes each
backup schedule to its own app happens on the `docker-volume-backup`
side, not in the proxy's own grant.
