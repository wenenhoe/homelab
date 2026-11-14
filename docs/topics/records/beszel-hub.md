# Beszel Hub: Service Record

The hub of the host and container monitor, running once on `security`. The connection model, key and token bootstrap and rebuild steps are in [`beszel.md`](../monitoring/beszel.md); the catalog's facts are in the [coverage table](../disaster-recovery/coverage.md).

## Dependencies

- Needs the `caddy-proxy` network, the `data` volume and its `.env`. The agent `KEY` and `TOKEN` exist only after the hub's first boot and are entered into OpenBao by hand ([`beszel.md`](../monitoring/beszel.md#bootstrapping-the-key-and-token)).
- Needed by every `beszel-agent`, which connects out to it. If the hub is down the agents retry and no history is collected.

## Data

- A PocketBase database in `data`: the admin account, every system's monitoring history, the notification channels (including the Telegram bot token) and the saved agent fingerprints. The bot token is a secret.
- The agent key and token also live inside this database ([`beszel.md`](../monitoring/beszel.md#rotating-the-key-and-token)).

## Exposure

- Its Caddy route sets `auth: false`, because the agent handshake at `/api/beszel/agent-connect` is machine to machine and Tinyauth would block it. The dashboard is gated by the hub's own login ([`beszel.md`](../monitoring/beszel.md#why-the-hub-skips-tinyauth)).
- Outbound, it sends alerts to Telegram ([`telegram-notifications.md`](../monitoring/telegram-notifications.md)).
- It drops every capability and exposes port 8090 to Caddy only.

## Threat model

- Anyone who reaches the route can attempt the hub login or the handshake. The handshake needs the token and the hub's key, and the dashboard needs the admin password. Unknown: whether the login has rate limiting; check PocketBase's settings.
- A stolen agent token lets a rogue host report as a system. The fingerprint a system first connects with is saved, so a different machine is refused ([`beszel.md`](../monitoring/beszel.md#rebuilding-a-host)).
- Rotating the key or token means wiping the volume and redoing the bootstrap.

## Observability

- The hub's own health check runs in the container, and the `security` agent reports the container, but both come from the hub itself. Unknown: what alerts if the hub is down. Check for an external probe; Gatus's endpoints are heartbeats ([`gatus.md`](../monitoring/gatus.md)).
- It is the notifier for the host and container monitoring topic, so a failure that stops it raises no alert from here.

## Disaster recovery

Backed up: `data` at the default schedule, with the container stopped while it is archived ([`backup.md`](../disaster-recovery/backup.md)). After a rebuild of `security`, restore the hub first so the fingerprint can be fixed ([`beszel.md`](../monitoring/beszel.md#rebuilding-a-host)). Acceptable loss and downtime: Unknown; check [`exercises.md`](../disaster-recovery/exercises.md).

## Lifecycle

- Upgrade: bump the pinned image in the compose file and deploy; the hub and agents share a minor version, so bump both.
- Removal: the agents keep retrying without effect; remove them from the catalog entry's hosts too.
- Waits on nothing at start. A first deploy leaves the agents in an auth-retry loop until the key and token are entered.
