# OpenBao: Service Record

The secrets store: a single-node OpenBao with integrated raft storage on `security`. How it is deployed, initialised and unsealed is in [`openbao.md`](../secrets/openbao.md); this record answers the integration questions and links where each is owned. What the catalog declares (host, volumes) is in the [coverage table](../disaster-recovery/coverage.md).

## Dependencies

- Needs `step-ca` for its listener certificate. The container crash-loops until `step_ca_cert` issues it, so a fresh `security` brings up `step-ca` first ([`openbao.md`](../secrets/openbao.md#first-bring-up-order)).
- Needs the `caddy-proxy` Docker network and the `data`, `config` and `certs` volumes.
- Needs an operator to unseal it after every restart ([`openbao.md`](../secrets/openbao.md#init-and-unseal--manual-via-initpy-and-unsealpy)).
- Needed by the `secrets` role and every playbook that reads a secret, the CD agent's AppRoles, and the Gatus tokens ([`secrets.md`](../secrets/secrets.md), [`openbao-cd-agent-approles.md`](../secrets/openbao-cd-agent-approles.md)). Restores need it too, for their S3 keys.

## Data

Holds every secret the repository generates or caches, in its raft dataset on the `data` volume. The unseal shares and the initial root token are created once by `init.py`, which prints them to the operator's terminal and never writes them down; the operator keeps them outside the host ([`openbao.md`](../secrets/openbao.md)).

## Exposure

- The listener is published directly on the host, not through Caddy, and has no Tinyauth route: a client reaches it with an AppRole or token ([`openbao-auth.md`](../secrets/openbao-auth.md)).
- Its TLS certificate comes from `step-ca` and is renewed by a systemd timer ([`openbao.md`](../secrets/openbao.md#tls)).
- Outbound, the `rotation-read-watcher` alerts on reads of the three rotation credentials, for R2, B2 and OCI ([`openbao-rotation-read-watcher.md`](../secrets/openbao-rotation-read-watcher.md)); the snapshot script pushes to R2 and B2 with a no-delete write credential ([`openbao-backup-restore.md`](../secrets/openbao-backup-restore.md#push-credential)).
- The container drops all capabilities except the one it needs and sets `no-new-privileges`; the reasons are in [`container-hardening.md`](../deploy/container-hardening.md).

## Threat model

- An attacker with the unseal shares and the raft data reads every secret. The shares are never stored on the host, and the data is only encrypted at rest by the seal.
- A stolen or over-broad token reads or writes secrets. Clients use AppRoles with their own policies (the CD agent's are bound to a CIDR), and the initial root token is revoked after setup ([`openbao-auth.md`](../secrets/openbao-auth.md), [`openbao-cd-agent-approles.md`](../secrets/openbao-cd-agent-approles.md)).
- A read of the high-value secrets is noticed through the audit device and the rotation read watcher ([ADR 0026](../../decisions/0026-detecting-reads-of-high-value-secrets/revision-001.md)).
- Unknown: whether the audit log stream is retained anywhere beyond the container's log rotation. Check the `logging:` block of the compose file and the host's log shipping.

## Observability

- A sealed or crashed instance fails its container health check, which Beszel reports as container state ([`beszel.md`](../monitoring/beszel.md)).
- Its certificate renewer pushes a daily heartbeat (`cert-renewer-openbao`) and Gatus alerts to Telegram when it stops ([`gatus.md`](../monitoring/gatus.md)).
- Unknown: whether anything alerts on a seal that happens without a container restart. Check the Gatus endpoints and the Beszel alert rules.

## Disaster recovery

Recovery tier 1 (`recovery_tier: 1` in the catalog). It has no `backup` entry, because stopping it to archive its volume would seal it. Its backup is a raft snapshot pushed to R2 and B2 by a script the operator runs ([`openbao-backup-restore.md`](../secrets/openbao-backup-restore.md)). The restore drill and the rebuild of `security` from nothing are in the same doc and in [`openbao-reinit-runbook.md`](../secrets/openbao-reinit-runbook.md). Unseal after a restore is by hand ([`rebuild-runbook.md`](../disaster-recovery/rebuild-runbook.md#still-done-by-hand)). Acceptable loss and downtime: Unknown; check [ADR 0111](../../decisions/0111-recovering-the-secrets-store-from-total-loss/revision-000.md) and [`exercises.md`](../disaster-recovery/exercises.md).

## Lifecycle

- Upgrade: bump the pinned image in the compose template, deploy, then unseal ([`openbao.md`](../secrets/openbao.md)). `maintenance.yaml` leaves `security` unrebooted so the operator reboots and unseals.
- Removal: not documented. Unknown: check whether `cleanup.yaml` is safe for this app; its `data` volume must never be wiped outside a restore.
- Waits on `step-ca` for its certificate, and on the operator for the unseal.
