---
id: ADR-0004
revision: 0
type: adr
title: Container access to the Docker API
short: Docker API access
solution: A per-consumer docker-socket-proxy sidecar, never the raw socket
summary: Containers that need the Docker API get only the capabilities they use, never control of every container on the host.
topic: deployment-platform
status: superseded
superseded_by: 1
related: [ADR-0009]
---

# 0004. Container access to the Docker API

## Decision

Replace every direct Docker-socket mount with a
`tecnativa/docker-socket-proxy` sidecar, scoped per consumer to only
the specific API capabilities it actually needs (e.g. `diun` gets
`CONTAINERS=1 IMAGES=1` — list containers and images, nothing else;
`backup_agent` additionally needs `POST=1` to stop/start containers
around a snapshot). No app ever mounts the real socket itself.
