# Beszel Agent: Service Record

The per-host agent that reports host and container metrics to the hub; it runs on every managed host, including `security`. The connection model and bootstrap are in [`beszel.md`](../monitoring/beszel.md); the catalog's facts are in the [coverage table](https://wenenhoe.github.io/homelab/dr-coverage/).

## Dependencies

- Needs the Beszel hub's URL, and the `KEY` and `TOKEN` in its `.env`, which come from OpenBao ([`beszel.md`](../monitoring/beszel.md#bootstrapping-the-key-and-token)).
- Needs a `docker-socket-proxy` sidecar with the Docker socket mounted read-only for container statistics, and the host network for interface statistics.
- Needed by nothing else; the hub depends on it for data.

## Data

- A `data` volume holding the agent's fingerprint. The `KEY` and `TOKEN` are secrets in the agent's `.env`, which is mode `0600`.
- It reads host and container metrics and sends them to the hub; it stores no history.

## Exposure

- It runs on the host network but opens no listening port, since SSH mode is disabled; it connects outbound to the hub over a WebSocket ([`beszel.md`](../monitoring/beszel.md#connection-model)).
- The sidecar publishes the proxied Docker API on `127.0.0.1:2375`, and the agent runs on the host network, so any process on the host can reach it.
- Both containers drop every capability.

## Threat model

- A compromised agent can send false metrics for its own system only; it holds a token, not the hub's keys.
- The proxy allows `CONTAINERS=1`, which admits more than metadata: reading a container's inspect data, logs and archive, which reveal its environment, output and files ([ADR 0004](../../decisions/0004-container-access-to-the-docker-api/revision-001.md)). The socket is mounted read-only, which does not narrow those reads ([`beszel.md`](../monitoring/beszel.md#runtime-config)). A rules file naming only the calls the agent makes is planned ([`beszel-agent-docker-api-rules.md`](../../projects/beszel-agent-docker-api-rules.md)).
- The port is bound to the loopback address, so another host reaches it only through something running on the host itself.

## Observability

- The agent's container health check runs in the container, and the hub shows a system as down when its agent stops reporting.
- A rebuilt host's agent fails with a fingerprint mismatch and logs it on every retry ([`beszel.md`](../monitoring/beszel.md#rebuilding-a-host)).

## Disaster recovery

Not backed up; recovery tier 3. A redeploy restores the agent, and the fingerprint on the hub must be updated by hand for a rebuilt host ([`rebuild-runbook.md`](../disaster-recovery/rebuild-runbook.md#still-done-by-hand)). Acceptable loss and downtime: Unknown.

## Lifecycle

- Upgrade: bump the pinned images in the compose file and deploy; keep the agent at the hub's version.
- Removal: remove the host's entry and the system from the hub's dashboard.
- Waits on the hub having a key and token, or it retries.
