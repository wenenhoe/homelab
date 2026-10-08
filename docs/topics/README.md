# Topic docs

What is true on `main` now, one doc per subject, grouped by what it is about. Look where you would be working: a runbook sits with the thing it operates, not in a folder of runbooks. Each doc has one home; other docs link to it rather than repeating it.

A group that outgrows a flat folder can nest a subfolder for one cluster. Every doc under here, at any depth, is listed below — [`check_doc_drift.py`](../../tools/doc_scripts/check_doc_drift.py) fails on one that isn't, or on a link that points nowhere.

## deploy/

Deploying apps: how the Ansible and Compose pipeline works and how to extend it.

| Doc | Covers |
| :--- | :--- |
| [`ansible.md`](deploy/ansible.md) | Playbook, role, and inventory reference tables. |
| [`deployment-flow.md`](deploy/deployment-flow.md) | The `deploy.yaml` play sequence, role responsibilities, `app_catalog`. |
| [`adding-an-app.md`](deploy/adding-an-app.md) | Wiring a new Compose app into the catalog. |
| [`host-vars.md`](deploy/host-vars.md) | `host_vars/<host>.yaml` field reference. |
| [`volumes.md`](deploy/volumes.md) | Named-volume storage: bind-mount migration, config seeding. |
| [`volume-maintenance.md`](deploy/volume-maintenance.md) | Ad hoc in-place volume file removal/reset outside `cleanup.yaml`. |
| [`cleanup.md`](deploy/cleanup.md) | Removing stacks orphaned from `compose_apps`. |
| [`cd-agent-host.md`](deploy/cd-agent-host.md) | The `cd_agent` role: per-job users, sandboxed units and timers, and the `sshd` restriction to the operator host. |
| [`cd-agent-runner.md`](deploy/cd-agent-runner.md) | The CD agent's per-job poll, decide and run step: what a run fetches, checks out, runs and records. |

## infra/

Machines and what sits beneath the apps: hosts, network, hypervisor, provisioning.

| Doc | Covers |
| :--- | :--- |
| [`vm-provisioning.md`](infra/vm-provisioning.md) | **Planned, not yet implemented.** Design record for OpenTofu-driven Proxmox VM provisioning: VMID/VLAN/IP/MAC scheme, Ubuntu/OPNsense design, Tofu↔Ansible boundary. Build status: the `tofu-vm-provisioning` initiative in [`project-planning.md`](../project-planning.md#super-projects). |
| [`network-infra.md`](infra/network-infra.md) | The `network_infra`/`patched_hosts` inventory groups: non-app hosts like the Tailscale subnet router, and their bootstrap prerequisites. |
| [`host-hardening.md`](infra/host-hardening.md) | The `host_hardening` role: its allow-list of `konstruktoid.hardening` areas, what each sets, where `maintenance.yaml` applies it, and how to verify a host. |
| [`qemu-guest-agent.md`](infra/qemu-guest-agent.md) | Installing `qemu-guest-agent` for Proxmox VM integration. |
| [`netplan-dhcp-identifier.md`](infra/netplan-dhcp-identifier.md) | Current-fleet-only fix for a DHCP dual-lease bug on boot; not Ansible-managed, transitional until the Tofu migration decommissions these hosts. |

## services/

Platform services the apps depend on: DNS, ingress, identity, PKI.

| Doc | Covers |
| :--- | :--- |
| [`bind9.md`](services/bind9.md) | Internal DNS zone aggregation and rendering. |
| [`caddy.md`](services/caddy.md) | Custom Caddy build, Caddyfile generation, Tinyauth wiring. |
| [`lldap.md`](services/lldap.md) | LDAPS cert lifecycle via step-ca and a systemd renewal timer; bootstrapping the observer account tinyauth binds as. |
| [`step-ca.md`](services/step-ca.md) | Internal PKI: bootstrap, provisioner claims, requesting a cert. |
| [`wastebin.md`](services/wastebin.md) | Custom wastebin image: adding a static `wget` to a `FROM scratch` base for healthchecks. |

## secrets/

OpenBao and the credentials around it.

| Doc | Covers |
| :--- | :--- |
| [`secrets.md`](secrets/secrets.md) | The `secrets` role, `openbao_utils/bootstrap.py`, rotation. |
| [`secrets-rotation.md`](secrets/secrets-rotation.md) | Rotating a generated secret, a manual credential, or a cert-backed volume — which mechanism applies and which host(s) each one needs redeployed. |
| [`cloud-credentials/creation.md`](secrets/cloud-credentials/creation.md) | The scripts that mint, audit and verify the R2/B2/OCI credentials, and how to run them. |
| [`cloud-credentials/scoping.md`](secrets/cloud-credentials/scoping.md) | What each provider's master credential can be narrowed to, and what the rotation and leaf credentials are scoped to. |
| [`cloud-credentials/rotation.md`](secrets/cloud-credentials/rotation.md) | How the leaf and rotation credentials rotate, per provider: the `--rotate` flow, its verification, and rotating the rotation credential itself. |
| [`cloud-credentials/expiry.md`](secrets/cloud-credentials/expiry.md) | The 90-day credential expiry, the weekly freshness check, and the Telegram warning ladder. |
| [`openbao.md`](secrets/openbao.md) | OpenBao deployment, TLS cert lifecycle, manual init/unseal runbook. |
| [`openbao-auth.md`](secrets/openbao-auth.md) | `controller`'s AppRole/policy setup and revoking the initial root token. |
| [`openbao-cd-agent-approles.md`](secrets/openbao-cd-agent-approles.md) | The four CIDR-bound AppRoles for `cd_agent` (deploy, rotation, freshness, snapshot): their policies, how to create them, and handing over a wrapped `secret_id`. |
| [`openbao-vault-bootstrap.md`](secrets/openbao-vault-bootstrap.md) | The standing `vault-bootstrap` AppRole for minting new Vault policies/AppRoles, and its emergency-root mechanism. |
| [`openbao-backup-restore.md`](secrets/openbao-backup-restore.md) | OpenBao's own raft-snapshot backup/restore mechanism and drill runbook. |
| [`openbao-reinit-runbook.md`](secrets/openbao-reinit-runbook.md) | One-time procedure for discarding and rebuilding OpenBao's raft dataset from scratch (ADR 0025) — distinct from the restore drill. |
| [`openbao-r2-read-watcher.md`](secrets/openbao-r2-read-watcher.md) | ADR 0026's per-read alert on the R2 rotation token: what it watches, installation, and the still-open gap in alerting when the watcher itself stops running. |

## disaster-recovery/

Backup, offsite copies, and getting data back.

| Doc | Covers |
| :--- | :--- |
| [`backup.md`](disaster-recovery/backup.md) | SeaweedFS target, `backup_agent`, GPG encryption, what is backed up and where it goes. |
| [`backup-threat-model.md`](disaster-recovery/backup-threat-model.md) | The adversary the backup design assumes, the credential-scoping constraints that follow, and the automated coverage for them. |
| [`restore.md`](disaster-recovery/restore.md) | Restoring an app's volume(s) from a backup archive: the runbook. |
| [`fire-drill.md`](disaster-recovery/fire-drill.md) | Proving the restore path actually works: automated coverage vs. a real fire drill, and how to run one without touching production. |
| [`cloud-sync.md`](disaster-recovery/cloud-sync.md) | Offsite replication to R2/B2/OCI: mechanism, retention, first-use setup. |

## monitoring/

Observability and alerting.

| Doc | Covers |
| :--- | :--- |
| [`beszel.md`](monitoring/beszel.md) | Hub/agent monitoring, KEY/TOKEN bootstrap. |
| [`telegram-notifications.md`](monitoring/telegram-notifications.md) | Bot/topic scheme shared by diun, Beszel, backups, and cert-renewal alerts. |
| [`uptime-kuma.md`](monitoring/uptime-kuma.md) | Push-monitor dead-man's-switch status per job, routed into the Telegram topics above. |

## engineering/

Working on the repo: conventions, tests, CI, review and scanning.

| Doc | Covers |
| :--- | :--- |
| [`conventions.md`](engineering/conventions.md) | Naming and structural rules that span more than one component: Ansible vs. Docker/systemd casing, Vault KV paths, systemd unit layout, Telegram topics, Python unit test style. |
| [`pre-commit.md`](engineering/pre-commit.md) | The pre-commit hooks and what each checks, which stage runs when, and where each tool's config lives. |
| [`ci/pipeline.md`](engineering/ci/pipeline.md) | The PR-checks pipeline: where the CI logic lives, the job list, cache warming, and which checks to require before merge. |
| [`ci/change-scoping.md`](engineering/ci/change-scoping.md) | How a change decides which jobs run: the scoped outputs `detect-changes` produces, Molecule watch sets, and the comment-only and formatting-only changes that queue nothing. |
| [`ci/gates.md`](engineering/ci/gates.md) | The regression checks and gates over one kind of change: deploy ordering, secret and app catalog rules, Molecule coverage, compose boot-testing, Dockerfile builds and image tags. |
| [`ci/doc-checks.md`](engineering/ci/doc-checks.md) | Index generation, the docs drift check, and the project scope and close checks. |
| [`ci/scheduled-jobs.md`](engineering/ci/scheduled-jobs.md) | The Renovate window check and Trivy scanning. |
| [`mutation-testing.md`](engineering/mutation-testing.md) | When a mutation run is worth making on the credential tooling, how to read a survivor, and why its output stays off public surfaces. |
| [`molecule-testing.md`](engineering/molecule-testing.md) | Molecule scenario matrix and how to add one. |
| [`molecule-fixtures.md`](engineering/molecule-fixtures.md) | How fixtures avoid duplicating prod compose files, `app_catalog` entries, and placeholder shapes; `molecule_helpers`' shared task files and DinD test-container internals. |
| [`security-scanning.md`](engineering/security-scanning.md) | Trivy Ansible-misconfig and secret scanning: report-only, scheduling, known scanner quirks. |
| [`security-findings.md`](engineering/security-findings.md) | The private `homelab-security` tracker for code-review findings: what it holds, the contract a writer follows, how findings are triaged, and how this repo may refer to them. |
| [`coderabbit-review.md`](engineering/coderabbit-review.md) | Containerized CodeRabbit CLI review of a PR's diff, run from `homelab-security`'s CI or by hand: auth, the CI-built image, why output stays off this repo's own surfaces. |
| [`nist-800-53-alignment.md`](engineering/nist-800-53-alignment.md) | Selective, narrative NIST SP 800-53 alignment — which existing decisions resemble which control's intent, and one control evaluated and left unmapped. Not a compliance artifact. |
