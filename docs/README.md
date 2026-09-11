# Docs: where things go

This repo's docs stay flat under `docs/`, plus three subdirectories for
artifact types that don't fit a per-topic page:

- **[`decisions/`](decisions/README.md)** — why a design was chosen,
  when the reasoning isn't obvious from the code. One file per decision,
  numbered, never edited after acceptance (superseded instead).
- **[`architecture/`](architecture/README.md)** — Mermaid diagrams for
  views that cut across multiple topic docs (a system-wide component
  map, an end-to-end data flow). A diagram that only illustrates one
  existing page lives embedded in that page instead.
- **[`projects/`](projects/README.md)** — build status and sequencing
  for multi-stage initiatives spanning several PRs. Never carries
  rationale (that's `decisions/`) or current-behavior detail (that's a
  topic doc) — it links to both instead, and gets deleted once the
  project's done and everything durable has been promoted out of it.

Everything else is one topic, one doc, cross-referenced rather than
duplicated — if you're about to explain the same gotcha in a second
place, link to the first instead.

**Every doc's source of truth is the code/config it describes, checked
by [`check-doc-drift.py`](../.github/scripts/check-doc-drift.py)** for
the handful of places that check mechanically (this index and each
subdirectory's own, `ansible.md`'s playbook table, the molecule
scenario matrix, the deploy play numbering, `ci.md`'s job table, and
every cross-file `#anchor` reference repo-wide). Nothing here enforces
the rest by tooling — that's still on whoever's making the change to
keep current in the same PR, the same way a diagram's topology should
change alongside the topology it shows (see `architecture/README.md`'s
note on that).

## Index

### Architecture & workflow

| Doc | Covers |
| :--- | :--- |
| [`ansible.md`](ansible.md) | Playbook, role, and inventory reference tables. |
| [`deployment-flow.md`](deployment-flow.md) | The `deploy.yaml` play sequence, role responsibilities, `app_registry`. |
| [`volumes.md`](volumes.md) | Named-volume storage: bind-mount migration, config seeding. |
| [`host-vars.md`](host-vars.md) | `host_vars/<host>.yaml` field reference. |
| [`adding-an-app.md`](adding-an-app.md) | Wiring a new Compose app into the registry. |

### Planned, not yet implemented

| Doc | Covers |
| :--- | :--- |
| [`vm-provisioning.md`](vm-provisioning.md) | Design record for OpenTofu-driven Proxmox VM provisioning: VMID/VLAN/IP/MAC scheme, Ubuntu/OPNsense design, Tofu↔Ansible boundary. Build status: [`projects/tofu-vm-provisioning.md`](projects/tofu-vm-provisioning.md). |

### Per-app infra

| Doc | Covers |
| :--- | :--- |
| [`bind9.md`](bind9.md) | Internal DNS zone aggregation and rendering. |
| [`caddy.md`](caddy.md) | Custom Caddy build, Caddyfile generation, Tinyauth wiring. |
| [`beszel.md`](beszel.md) | Hub/agent monitoring, KEY/TOKEN bootstrap. |
| [`telegram-notifications.md`](telegram-notifications.md) | Bot/topic scheme shared by diun, Beszel, backups, and cert-renewal alerts. |
| [`uptime-kuma.md`](uptime-kuma.md) | Push-monitor dead-man's-switch status per job, routed into the Telegram topics above. |
| [`lldap.md`](lldap.md) | LDAPS cert lifecycle via step-ca and a systemd renewal timer; bootstrapping the observer account tinyauth binds as. |
| [`step-ca.md`](step-ca.md) | Internal PKI: bootstrap, provisioner claims, requesting a cert. |
| [`openbao.md`](openbao.md) | OpenBao deployment, TLS cert lifecycle, manual init/unseal runbook. |
| [`openbao-backup-restore.md`](openbao-backup-restore.md) | OpenBao's own raft-snapshot backup/restore mechanism and drill runbook. |
| [`openbao-auth.md`](openbao-auth.md) | `controller`'s AppRole/policy setup and revoking the initial root token. |
| [`openbao-vault-bootstrap.md`](openbao-vault-bootstrap.md) | The standing `vault-bootstrap` AppRole for minting new Vault policies/AppRoles, and its emergency-root mechanism. |
| [`openbao-reinit-runbook.md`](openbao-reinit-runbook.md) | One-time procedure for discarding and rebuilding OpenBao's raft dataset from scratch (ADR 0025) — distinct from the restore drill. |
| [`openbao-r2-read-watcher.md`](openbao-r2-read-watcher.md) | ADR 0026's per-read alert on the R2 rotation token: what it watches, installation, and the still-open `OnFailure=` gap. |
| [`wastebin.md`](wastebin.md) | Custom wastebin image: adding a static `wget` to a `FROM scratch` base for healthchecks. |
| [`qemu-guest-agent.md`](qemu-guest-agent.md) | Installing `qemu-guest-agent` for Proxmox VM integration. |

### Operations

| Doc | Covers |
| :--- | :--- |
| [`cleanup.md`](cleanup.md) | Removing stacks orphaned from `compose_apps`. |
| [`disaster-recovery.md`](disaster-recovery.md) | Stage 1 DR: SeaweedFS, `backup_agent`, GPG encryption. |
| [`restore.md`](restore.md) | Restoring an app's volume(s) from a backup archive: the runbook. |
| [`fire-drill.md`](fire-drill.md) | Proving the restore path actually works: automated coverage vs. a real fire drill, and how to run one without touching production. |
| [`cloud-sync.md`](cloud-sync.md) | Offsite replication to R2/B2/OCI: mechanism, retention, first-use setup. |
| [`cloud-credential-creation.md`](cloud-credential-creation.md) | Creating the 6 R2/B2/OCI write+read credentials via each provider's HTTP API, what each is scoped to, rotation. |
| [`volume-maintenance.md`](volume-maintenance.md) | Ad hoc in-place volume file removal/reset outside `cleanup.yaml`. |
| [`secrets.md`](secrets.md) | The `secrets` role, `bootstrap_secrets.py`, rotation. |
| [`secrets-rotation.md`](secrets-rotation.md) | Rotating a generated secret, a manual credential, or a cert-backed volume — which mechanism applies and which host(s) each one needs redeployed. |
| [`netplan-dhcp-identifier.md`](netplan-dhcp-identifier.md) | Current-fleet-only fix for a DHCP dual-lease bug on boot; not Ansible-managed, transitional until the Tofu migration decommissions these hosts. |

### Testing & CI

| Doc | Covers |
| :--- | :--- |
| [`molecule-testing.md`](molecule-testing.md) | Molecule scenario matrix and how to add one. |
| [`molecule-fixtures.md`](molecule-fixtures.md) | How fixtures avoid duplicating prod compose files, `app_registry` entries, and placeholder shapes; `molecule_helpers`' shared task files and DinD test-container internals. |
| [`ci.md`](ci.md) | The PR-checks pipeline: change-scoped jobs, boot-testing, deploy-ordering regression check. |
| [`security-scanning.md`](security-scanning.md) | Trivy Ansible-misconfig and secret scanning: report-only, scheduling, known scanner quirks. |
