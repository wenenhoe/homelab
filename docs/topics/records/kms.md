# KMS: Service Record

A Windows and Office activation emulator with a web console, on `services`. The catalog's facts are in the [coverage table](../disaster-recovery/coverage.md); there is no other topic doc for it.

## Dependencies

- Needs the `caddy-proxy` network for the console, the `data` volume shared by its two containers and the backup agent's label to stop it during a backup. Needed by nothing.

## Data

- The activation emulator's state in `data`. It holds no secret that this record can name. Unknown: what the state contains; check the image's documentation.

## Exposure

- Port 1688 is published on every interface of `services` for activation clients. The console is reached through Caddy behind Tinyauth and exposes port 3000 to Caddy only.
- Both containers run as `1000:1000` and drop every capability.

## Threat model

- The activation port answers any client that can reach it, with no authentication in the protocol. Unknown: which networks can reach port 1688; check the host firewall and the gateway rules in [`network-infra.md`](../infra/network-infra.md).
- The console shows its state to anyone with a Tinyauth login.

## Observability

- Container health states are reported by Beszel ([`beszel.md`](../monitoring/beszel.md)), and the archive is covered by the host's backup heartbeat ([`gatus.md`](../monitoring/gatus.md)). Nothing checks that activation itself works.

## Disaster recovery

Backed up: `data`, with both containers stopped during the archive ([`backup.md`](../disaster-recovery/backup.md)). Restored on 2026-11-06 on the rebuilt `services`; the drill did not use the app afterwards or compare the contents ([`fire-drill.md`](../disaster-recovery/fire-drill.md)). Acceptable loss and downtime: Unknown; check [`exercises.md`](../disaster-recovery/exercises.md).

## Lifecycle

- Upgrade: bump both pinned image tags together and deploy.
- Removal: delete its catalog entry and run `cleanup.yaml`; clients must be pointed elsewhere first ([`cleanup.md`](../deploy/cleanup.md)).
- Waits on the main container before the console.
