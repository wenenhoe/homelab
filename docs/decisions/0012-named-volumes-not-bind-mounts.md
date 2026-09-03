# 0012. Docker named volumes instead of bind mounts

**Status:** Accepted

## Context

The original design bind-mounted host paths directly into containers
(`./data:/data`-style). This produced recurring file-permission
friction: a container process running as a specific UID/GID inside the
image needs the host-side directory to already have matching
ownership, or writes fail — the BIND9 role's own fix a month earlier
(creating a host-level `bind` user at uid/gid `9970` purely to match
what the `ubuntu/bind9` image expected on disk) is a direct instance
of this class of problem, not a one-off.

Offsite backup coverage was also being planned around this time.
Nearly every viable backup tool in the Docker ecosystem — including
[`offen/docker-volume-backup`](https://github.com/offen/docker-volume-backup),
which this repo went on to adopt (see
[`disaster-recovery.md`](../disaster-recovery.md)) — operates on named
volumes, not arbitrary bind-mount host paths. Building the backup
design around bind mounts would have meant bespoke per-app path
discovery instead of a generic "mount whatever volumes this app
declares" agent.

A move to Kubernetes was considered around the same time and rejected:
this lab didn't (and doesn't) have multiple machines to actually
cluster, and the switch would have meant reworking most of this
repo's Compose-shaped tooling (the `docker_compose_v2`/`docker_container`
Ansible modules, the `docker-socket-proxy` sidecar pattern, the backup
agent's Compose-based design) for Kubernetes-native equivalents —
a materially larger undertaking than fixing the permission and backup
problems directly in front of it.

## Decision

Move persistent app state to Docker-managed named volumes, created and
populated by Ansible (see [`volumes.md`](../volumes.md)), instead of
host bind mounts.

## Consequences

Docker owns each volume's on-disk permissions instead of requiring the
host-side directory's ownership to be pre-arranged to match whatever
UID a given image happens to run as — the class of problem the BIND9
fix above worked around manually no longer needs a per-app manual fix.
Volumes are also now labelable and discoverable by Docker's own volume
API, which is what makes `backup_agent`'s generic "back up whatever
volumes this app declares" design possible at all (see
[`disaster-recovery.md`](../disaster-recovery.md)) and what
[`cleanup.md`](../cleanup.md) uses to find orphaned volumes.

The Kubernetes path stays rejected on the same basis until the
underlying constraint changes — specifically, having enough machines
to actually form a cluster, not any tooling gap. (One thing worth
correcting for the record: `diun` specifically would not have forced
this either way — it ships its own native Kubernetes provider,
watching pod annotations via a scoped `ClusterRole` instead of the
Docker socket, so it wasn't a real blocker on its own.)
