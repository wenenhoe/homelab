# Docs: where things go

This repo's docs stay flat under `docs/`, plus three subdirectories for
artifact types that don't fit a per-topic page:

- **[`decisions/`](decisions/README.md)** — why a design was chosen,
  when the reasoning isn't obvious from the code. One lineage per
  problem, one revision per solution tried for it; an `accepted`
  revision's reasoning stays fixed — a changed decision is a new
  revision — while editorial fixes are fine. See
  [`decisions/README.md#editing-a-revision`](decisions/README.md#editing-a-revision)
  for where that line sits.
- **[`architecture/`](architecture/README.md)** — Mermaid diagrams for
  views that cut across multiple topic docs (a system-wide component
  map, an end-to-end data flow). A diagram that only illustrates one
  existing page lives embedded in that page instead.
- **[`projects/`](projects/README.md)** — execution records for
  multi-stage work spanning several PRs: what remains, in what order,
  waiting on what, grouped into initiatives and ordered by dependency.
  Never carries rationale (that's `decisions/`) or current-behavior detail
  (that's a topic doc) — it links to both, and is deleted once the work is
  done and everything durable has been promoted out of it. It can also
  bound what its work may change (`allowed_paths`); see
  [`projects/README.md#scope`](projects/README.md#scope).

Everything else is one topic, one doc, cross-referenced rather than
duplicated — if you're about to explain the same gotcha in a second
place, link to the first instead.

Topic docs describe what is true on `main` at every commit, not what a
project is still building.

**Every doc's source of truth is the code/config it describes, checked
by [`check-doc-drift.py`](../.github/scripts/check-doc-drift.py)** for
the handful of places that check mechanically (this index and each
subdirectory's own, `ansible.md`'s playbook table, the molecule
scenario matrix, the deploy play numbering, `ci.md`'s job table, every
cross-file `#anchor` reference repo-wide, every `docs/decisions/` or
`docs/projects/` path written anywhere — comments included — and the
decision-lineage and project rules in
[`decisions/README.md`](decisions/README.md) and
[`projects/README.md`](projects/README.md)). What a change is allowed to
touch is checked separately, by
[`check-project-scope.py`](../.github/scripts/check-project-scope.py).
Nothing here enforces the rest by tooling — that's still on whoever's
making the change to keep current in the same PR, the same way a
diagram's topology should change alongside the topology it shows (see
`architecture/README.md`'s note on that).

## Public repo

This repository is public and git history is permanent. No doc, comment,
or commit message records a security incident, a live or recent
vulnerability, or an exposure window — including in ADRs, project risks,
and blockers. If a doc would need those specifics to be useful, leave it
unwritten and raise it privately.

## Index

### Architecture & workflow

| Doc | Covers |
| :--- | :--- |
| [`conventions.md`](conventions.md) | Naming and structural rules that span more than one component: Ansible vs. Docker/systemd casing, Vault KV paths, systemd unit layout, Telegram topics. |
| [`project-planning.md`](project-planning.md) | Generated cross-cutting views: projects with an initiative by build order, standalone projects, and open ADRs no project covers yet. |
| [`nist-800-53-alignment.md`](nist-800-53-alignment.md) | Selective, narrative NIST SP 800-53 alignment — which existing decisions resemble which control's intent, and one control evaluated and left unmapped. Not a compliance artifact. |
| [`ansible.md`](ansible.md) | Playbook, role, and inventory reference tables. |
| [`deployment-flow.md`](deployment-flow.md) | The `deploy.yaml` play sequence, role responsibilities, `app_registry`. |
| [`volumes.md`](volumes.md) | Named-volume storage: bind-mount migration, config seeding. |
| [`host-vars.md`](host-vars.md) | `host_vars/<host>.yaml` field reference. |
| [`network-infra.md`](network-infra.md) | The `network_infra`/`patched_hosts` inventory groups: non-app hosts like the Tailscale subnet router, and their bootstrap prerequisites. |
| [`adding-an-app.md`](adding-an-app.md) | Wiring a new Compose app into the registry. |

### Planned, not yet implemented

| Doc | Covers |
| :--- | :--- |
| [`vm-provisioning.md`](vm-provisioning.md) | Design record for OpenTofu-driven Proxmox VM provisioning: VMID/VLAN/IP/MAC scheme, Ubuntu/OPNsense design, Tofu↔Ansible boundary. Build status: the `tofu-vm-provisioning` initiative in [`project-planning.md`](project-planning.md#super-projects). |

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
| [`openbao-r2-read-watcher.md`](openbao-r2-read-watcher.md) | ADR 0026's per-read alert on the R2 rotation token: what it watches, installation, and the still-open gap in alerting when the watcher itself stops running. |
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
| [`secrets.md`](secrets.md) | The `secrets` role, `openbao_utils/bootstrap.py`, rotation. |
| [`secrets-rotation.md`](secrets-rotation.md) | Rotating a generated secret, a manual credential, or a cert-backed volume — which mechanism applies and which host(s) each one needs redeployed. |
| [`netplan-dhcp-identifier.md`](netplan-dhcp-identifier.md) | Current-fleet-only fix for a DHCP dual-lease bug on boot; not Ansible-managed, transitional until the Tofu migration decommissions these hosts. |

### Testing & CI

| Doc | Covers |
| :--- | :--- |
| [`molecule-testing.md`](molecule-testing.md) | Molecule scenario matrix and how to add one. |
| [`molecule-fixtures.md`](molecule-fixtures.md) | How fixtures avoid duplicating prod compose files, `app_registry` entries, and placeholder shapes; `molecule_helpers`' shared task files and DinD test-container internals. |
| [`ci.md`](ci.md) | The PR-checks pipeline: change-scoped jobs, boot-testing, deploy-ordering regression check, and the project-scope check. |
| [`security-scanning.md`](security-scanning.md) | Trivy Ansible-misconfig and secret scanning: report-only, scheduling, known scanner quirks. |
| [`coderabbit-review.md`](coderabbit-review.md) | Containerized CodeRabbit CLI review of a PR's diff, run from `homelab-security`'s CI or by hand: auth, the CI-built image, why output stays off this repo's own surfaces. |
