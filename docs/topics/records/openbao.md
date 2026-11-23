# OpenBao: Service Record

The secrets store: a single-node OpenBao with integrated raft storage on `security`. How it is deployed, initialised and unsealed is in [`openbao.md`](../secrets/openbao.md); this record answers the integration questions and links where each is owned. What the catalog declares (host, volumes) is in the [coverage table](https://wenenhoe.github.io/homelab/dr-coverage/).

## Dependencies

- Needs `step-ca` for its listener certificate. The container crash-loops until `step_ca_cert` issues it, so a fresh `security` brings up `step-ca` first ([`openbao.md`](../secrets/openbao.md#first-bring-up-order)).
- Needs the `caddy-proxy` Docker network and the `data`, `config` and `certs` volumes.
- Needs an operator to unseal it after every restart ([`openbao.md`](../secrets/openbao.md#init-and-unseal--manual-via-initpy-and-unsealpy)).
- Needed by the `secrets` role and every playbook that reads a secret, the CD agent's AppRoles, and the Gatus tokens ([`secrets.md`](../secrets/secrets.md), [`openbao-cd-agent-approles.md`](../secrets/openbao-cd-agent-approles.md)). Restores need it too, for their S3 keys.
- Needed by the `rotation-read-watcher` on the same host, which logs in once at start and restarts until the store is unsealed. The watcher is installed by hand, not by Ansible ([`openbao-rotation-read-watcher.md`](../secrets/openbao-rotation-read-watcher.md#installing)).

## Data

Holds every secret the repository generates or caches, in its raft dataset on the `data` volume. The unseal shares and the initial root token are created once by `init.py`, which prints them to the operator's terminal and never writes them down; the operator keeps them outside the host ([`openbao.md`](../secrets/openbao.md)).

## Exposure

- The listener is published directly on the host, not through Caddy, and has no Tinyauth route: a client reaches it with an AppRole or token ([`openbao-auth.md`](../secrets/openbao-auth.md)).
- It binds `0.0.0.0:8200`, every interface of `security`, except while the node is uninitialised: `bootstrap-security.yaml` binds it to `127.0.0.1` until then. The repository configures no host firewall ([ADR 0043](../../decisions/0043-host-os-hardening-baseline/revision-000.md)), so what can reach the port is set by the gateway's rules between VLANs ([ADR 0089](../../decisions/0089-how-the-opnsense-gateway-is-configured/revision-000.md)). Hosts on `security`'s own VLAN reach it with no rule in between, and sealed or not, the listener accepts connections.
- Its TLS certificate comes from `step-ca` and is renewed by a systemd timer ([`openbao.md`](../secrets/openbao.md#tls)).
- Outbound, the `rotation-read-watcher` alerts on reads of the three rotation credentials, for R2, B2 and OCI ([`openbao-rotation-read-watcher.md`](../secrets/openbao-rotation-read-watcher.md)); the snapshot script pushes to R2 and B2 with a no-delete write credential ([`openbao-backup-restore.md`](../secrets/openbao-backup-restore.md#push-credential)).
- The container drops all capabilities except the one it needs and sets `no-new-privileges`; the reasons are in [`container-hardening.md`](../deploy/container-hardening.md).

## Threat model

- An attacker with the unseal shares and the raft data reads every secret. The shares are never stored on the host, and the data is only encrypted at rest by the seal.
- A stolen or over-broad token reads or writes secrets. Clients use AppRoles with their own policies (the CD agent's are bound to a CIDR), and the initial root token is revoked after setup ([`openbao-auth.md`](../secrets/openbao-auth.md), [`openbao-cd-agent-approles.md`](../secrets/openbao-cd-agent-approles.md)).
- A read of the high-value secrets is noticed through the audit device and the rotation read watcher ([ADR 0026](../../decisions/0026-detecting-reads-of-high-value-secrets/revision-001.md)).
- The audit log goes to the container's output and is kept by the `json-file` driver, at most five files of 50 MB each. Nothing ships it off the host, and recreating the container, which any change to the compose file does, discards it. The rotation read watcher resumes from this log after a restart ([`openbao-rotation-read-watcher.md`](../secrets/openbao-rotation-read-watcher.md)).

## Observability

- A sealed or crashed instance fails its container health check, which Beszel reports as container state ([`beszel.md`](../monitoring/beszel.md)). Alerts on the hub are set by hand in its database ([`beszel.md`](../monitoring/beszel.md#alert-notifications)); the repository declares none and none has fired, so nothing alerts from this.
- Its certificate renewer pushes a daily heartbeat (`cert-renewer-openbao`) and Gatus alerts to Telegram when it stops ([`gatus.md`](../monitoring/gatus.md)).
- The rotation read watcher pushes a heartbeat (`rotation-read-watcher`) every 10 minutes, and Gatus alerts when it stops. The heartbeat checks that the watcher service is active. A stopped container or a restart that leaves the store sealed ends the watcher's log follower, its next login fails and the unit restarts every ten seconds, so the heartbeat stops. So does a start that cannot read Telegram's secrets, since the watcher exits rather than run with no way to alert. What the watcher cannot do while down, and why Gatus is the only alert for it, are in [`openbao-rotation-read-watcher.md`](../secrets/openbao-rotation-read-watcher.md#when-the-watcher-is-down).
- A seal while the container keeps running leaves the watcher running, so its heartbeat does not catch it. Unknown: whether anything else alerts on it. Check the Gatus endpoints.

## Disaster recovery

Recovery tier 1 (`recovery_tier: 1` in the catalog). It has no `backup` entry, because stopping it to archive its volume would seal it. Its backup is a raft snapshot pushed to R2 and B2 by a script the operator runs ([`openbao-backup-restore.md`](../secrets/openbao-backup-restore.md)). The restore drill and the rebuild of `security` from nothing are in the same doc and in [`openbao-reinit-runbook.md`](../secrets/openbao-reinit-runbook.md). Unseal after a restore is by hand, and so is the install of the rotation read watcher: until it is installed again on the rebuilt `security`, its heartbeat is missing and reads of the rotation credentials raise no alert ([`rebuild-runbook.md`](../disaster-recovery/rebuild-runbook.md#still-done-by-hand)). Acceptable loss and downtime: Unknown; check [ADR 0111](../../decisions/0111-recovering-the-secrets-store-from-total-loss/revision-000.md) and [`exercises.md`](../disaster-recovery/exercises.md).

## Lifecycle

- Upgrade: bump the pinned image in the compose template, deploy, then unseal ([`openbao.md`](../secrets/openbao.md)). `maintenance.yaml` leaves `security` unrebooted so the operator reboots and unseals.
- Removal: take `openbao` out of `security`'s `compose_apps`. `cleanup.yaml` then stops the stack and, with its default of `compose_cleanup_remove_content: false`, keeps the stack's directory and volumes ([`cleanup.md`](../deploy/cleanup.md)); its `data` volume, `openbao_data`, must never be wiped outside a restore. The hand-placed `openbao-backup` directory is on the playbook's exclusion list and is not touched.
- The image tag and digest are repeated in the `openbao` role's defaults, and the `openbao_cli` role pins the same version with the checksum of its `.deb`; an upgrade changes all of them together, and Renovate moves the CLI pair.
- Waits on `step-ca` for its certificate, and on the operator for the unseal.
