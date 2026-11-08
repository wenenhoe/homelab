# Beszel Agent: Service Record

The per-host agent that reports host and container metrics to the hub; it runs on every managed host, including `security`. The connection model and bootstrap are in [`beszel.md`](../monitoring/beszel.md); the catalog's facts are in the [coverage table](../disaster-recovery/coverage.md).

## Dependencies

- Needs the Beszel hub's URL, and the `KEY` and `TOKEN` in its `.env`, which come from OpenBao ([`beszel.md`](../monitoring/beszel.md#bootstrapping-the-key-and-token)).
- Needs a `docker-socket-proxy` sidecar with the Docker socket mounted read-only for container statistics, and the host network for interface statistics.
- Needed by nothing else; the hub depends on it for data.

## Data

- A `data` volume holding the agent's fingerprint. The `KEY` and `TOKEN` are secrets in the agent's `.env`, which is mode `0600`.
- It reads host and container metrics and sends them to the hub; it stores no history.

## Exposure

- It runs on the host network but opens no listening port, since SSH mode is disabled; it connects outbound to the hub over a WebSocket ([`beszel.md`](../monitoring/beszel.md#connection-model)).
- The sidecar publishes the proxied Docker API on a port. Unknown: which address the proxy binds to; check the compose file's `ports:` on each host.
- Both containers drop every capability.

## Threat model

- A compromised agent can send false metrics for its own system only; it holds a token, not the hub's keys.
- A reachable Docker API proxy exposes container metadata. The proxy is scoped to container reads and the socket is mounted read-only ([`beszel.md`](../monitoring/beszel.md#runtime-config)).
- Unknown: whether the proxy's published port is reachable from other hosts. Check the host firewall rules.

## Observability

- The agent's container health check runs in the container, and the hub shows a system as down when its agent stops reporting.
- A rebuilt host's agent fails with a fingerprint mismatch and logs it on every retry ([`beszel.md`](../monitoring/beszel.md#rebuilding-a-host)).

## Disaster recovery

Not backed up; recovery tier 3. A redeploy restores the agent, and the fingerprint on the hub must be updated by hand for a rebuilt host ([`rebuild-runbook.md`](../disaster-recovery/rebuild-runbook.md#still-done-by-hand)). It was brought up on the rebuilt `security` and `play` in the drills of 2026-11-01 and 2026-11-02; the first of these recorded no agent state ([`fire-drill.md`](../disaster-recovery/fire-drill.md)). Acceptable loss and downtime: Unknown.

## Lifecycle

- Upgrade: bump the pinned images in the compose file and deploy; keep the agent at the hub's version.
- Removal: remove the host's entry and the system from the hub's dashboard.
- Waits on the hub having a key and token, or it retries.
