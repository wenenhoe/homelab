# Project Planning

Four generated, cross-cutting views; none is a rules doc. For what a
project is and its lifecycle, see [`projects/README.md`](projects/README.md);
for what an ADR is and its revision states, see
[`decisions/README.md`](decisions/README.md).

**Unblocks**, in every table of projects, is the number of existing
projects that wait on that one, directly or through a chain of
`depends_on`; `—` means none does. It counts projects, not effort or
urgency.

**Status and Blocker**, in every table of projects, are two cells. Status is the
lifecycle status. Blocker says what stands in the way: `blocked:` and the
reason, `waiting on` the projects it depends on that still exist, or `waiting
on` its decision revision, named by its short name, when that is not yet
approved; more than one are joined with a semicolon. `—` means nothing does, so a not-started project with
`—` can be started. Neither cell is stored, per
[ADR 0082 (Choosing the next project)](decisions/0082-choosing-which-project-to-take-up-next/revision-001.md).

**Super Projects** groups every project that belongs to one
(`super_project:` is set) by build order — projects by dependency depth,
then by file name, per
[`projects/README.md`'s Hierarchy section](projects/README.md#hierarchy).
A repeated initiative name is blanked after its first row so the table
reads as one block per initiative.

**Projects** is every project with no `super_project` — the complement
of the view above, in the same shape as
[`projects/README.md`'s own Index](projects/README.md#index), filtered
down to the ones not part of any initiative. Both tables list building projects
first, then de-risking, not started and done, each by file name.

**Decisions awaiting a project** lists every ADR lineage with an open
(`working`/`approved`) revision that appears in no project's
`decision:` or `also_implements:` — see
[ADR 0037 revision 1 (Decision and project workflow)](decisions/0037-decision-and-project-documentation-workflow/revision-001.md)
for why those two fields specifically. A row here isn't automatically a
gap: some are correctly undecided and can't have a project yet, some
are single-PR-sized and don't need one, and this table can't see a
project that references the lineage only in prose without either field
set. It narrows where to look; it doesn't replace looking. Approved
revisions are listed first: one that no project names is the gap that
calls for a project, while a working one still has to be settled.

**Open explorations** lists every question in
[`explorations/`](explorations/README.md) with the date it last changed, oldest
first, so one that has stood still is the first row.

## Super Projects

| Initiative | Project | Unblocks | Status | Blocker |
| :--- | :--- | ---: | :--- | :--- |
| `backup-archive-protection` | [`backup-archive-retention-lock.md`](projects/backup-archive-retention-lock.md) | — | Not started | waiting on [ADR-0081/0 (On-site archive deletion)](decisions/0081-protecting-on-site-backup-archives-from-their-writer/revision-000.md) |
| | [`backup-archive-signing.md`](projects/backup-archive-signing.md) | — | Not started | waiting on [ADR-0079/0 (Backup archive authenticity)](decisions/0079-knowing-a-backup-archive-came-from-its-host/revision-000.md) |
| `coding-agent-host` | [`coding-agent-network.md`](projects/coding-agent-network.md) | 6 | Not started | waiting on [ADR-0053/0 (Coding-agent network reach)](decisions/0053-network-reach-of-the-coding-agent-host/revision-000.md) |
| | [`coding-agent-egress.md`](projects/coding-agent-egress.md) | — | Not started | waiting on [`coding-agent-network.md`](projects/coding-agent-network.md) |
| | [`coding-agent-host.md`](projects/coding-agent-host.md) | 4 | Not started | waiting on [`coding-agent-network.md`](projects/coding-agent-network.md) |
| | [`coding-agent-access-path.md`](projects/coding-agent-access-path.md) | — | Not started | waiting on [`coding-agent-host.md`](projects/coding-agent-host.md) |
| | [`coding-agent-management.md`](projects/coding-agent-management.md) | — | Not started | waiting on [`cd-agent.md`](projects/cd-agent.md), [`coding-agent-host.md`](projects/coding-agent-host.md) |
| | [`coding-agent-molecule-runtime.md`](projects/coding-agent-molecule-runtime.md) | — | Not started | waiting on [`coding-agent-host.md`](projects/coding-agent-host.md) |
| `compose-stack-files` | [`backup-agent-compose-app.md`](projects/backup-agent-compose-app.md) | — | Not started | waiting on [ADR-0088/0 (Role-deployed stack compose)](decisions/0088-where-a-role-deployed-stack-compose-file-lives/revision-000.md) |
| | [`beszel-agent-docker-api-rules.md`](projects/beszel-agent-docker-api-rules.md) | — | Not started | — |
| | [`compose-restart-on-changed-mount.md`](projects/compose-restart-on-changed-mount.md) | 1 | Not started | — |
| | [`bind-mounted-config-files.md`](projects/bind-mounted-config-files.md) | — | Not started | waiting on [`compose-restart-on-changed-mount.md`](projects/compose-restart-on-changed-mount.md) |
| `controller-separation` | [`operator-host.md`](projects/operator-host.md) | 2 | De-risking | — |
| | [`workstation-management.md`](projects/workstation-management.md) | — | Not started | — |
| | [`operator-host-takeover.md`](projects/operator-host-takeover.md) | — | Not started | waiting on [`operator-host.md`](projects/operator-host.md) |
| `off-site-monitoring` | [`gcp-e2-micro-provisioning.md`](projects/gcp-e2-micro-provisioning.md) | 1 | Not started | waiting on [ADR-0073/0 (Off-site cloud auth)](decisions/0073-how-provisioning-authenticates-to-the-off-site-cloud/revision-000.md) |
| | [`monitoring-host-isolation.md`](projects/monitoring-host-isolation.md) | — | Building | — |
| | [`off-site-monitoring.md`](projects/off-site-monitoring.md) | — | Not started | blocked: no production credential goes to the GCP host until its hardening pass is scoped and done; waiting on [`gcp-e2-micro-provisioning.md`](projects/gcp-e2-micro-provisioning.md) |
| `pull-based-cd` | [`cd-agent-approles.md`](projects/cd-agent-approles.md) | 1 | Building | — |
| | [`cd-agent-job-ssh-keys.md`](projects/cd-agent-job-ssh-keys.md) | — | Building | — |
| | [`cd-agent.md`](projects/cd-agent.md) | 3 | Building | — |
| | [`cd-agent-controller-approle-retirement.md`](projects/cd-agent-controller-approle-retirement.md) | — | Not started | waiting on [`cd-agent.md`](projects/cd-agent.md), [`cd-agent-approles.md`](projects/cd-agent-approles.md) |
| `tailnet-policy` | [`tailnet-policy-in-tofu.md`](projects/tailnet-policy-in-tofu.md) | — | Not started | waiting on [ADR-0059/0 (Tailnet policy)](decisions/0059-where-the-tailnet-policy-is-defined/revision-000.md) |
| `tofu-vm-provisioning` | [`opnsense-config.md`](projects/opnsense-config.md) | — | Building | — |
| | [`proxmox-node-install.md`](projects/proxmox-node-install.md) | — | Not started | waiting on [ADR-0093/0 (Proxmox node install)](decisions/0093-how-the-proxmox-node-is-installed-and-configured/revision-000.md) |
| | [`tofu-migration.md`](projects/tofu-migration.md) | — | Building | — |
| | [`windows-vms.md`](projects/windows-vms.md) | — | Not started | waiting on [ADR-0092/0 (Windows VM builds)](decisions/0092-how-windows-virtual-machines-are-built/revision-000.md) |

## Projects

| Project | Unblocks | Status | Blocker | Covers |
| :--- | ---: | :--- | :--- | :--- |
| [`dr-exercises.md`](projects/dr-exercises.md) | — | Building | — | Carry out the disaster-recovery exercise cadence: show each system's recovery tier and drill age in the coverage view, run the first quarter of exercises, and accept the decision. |
| [`integration-records.md`](projects/integration-records.md) | — | Building | — | A required-section topic doc for every integrated system, linked from the app catalog and checked, with a generated disaster-recovery coverage view. |
| [`automated-pr-review.md`](projects/automated-pr-review.md) | — | Not started | waiting on [ADR-0061/1 (Automated code review)](decisions/0061-where-automated-code-review-runs-and-what-it-may-write/revision-001.md) | Review a pull request from the private repository's CI when the maintainer labels it, describe the practice here, try it against the local CodeRabbit run, and accept the decision. |
| [`host-hardening-remaining-hosts.md`](projects/host-hardening-remaining-hosts.md) | — | Not started | waiting on [`operator-host.md`](projects/operator-host.md), [`cd-agent.md`](projects/cd-agent.md), [`coding-agent-host.md`](projects/coding-agent-host.md) | Confirm the operator host, the CD agent, and the coding-agent host include the hardening baseline from their own builds, then settle ADR 0043. |
| [`kms-image.md`](projects/kms-image.md) | — | Not started | waiting on [ADR-0091/0 (Activation host image)](decisions/0091-where-the-activation-hosts-image-comes-from/revision-000.md) | Build the Windows activation host's server-only image from the upstream py-kms in this repository, attest it, and replace the 11notes images and the kms-gui app. |
| [`licence-check.md`](projects/licence-check.md) | — | Not started | waiting on [ADR-0090/0 (Adopted software licences)](decisions/0090-licences-of-adopted-software/revision-000.md) | A registry of every pinned dependency's licence, a check when a pin changes, and a weekly check of each upstream's default-branch licence file, as ADR 0090 decides. |
| [`molecule-container-hardening.md`](projects/molecule-container-hardening.md) | — | Not started | — | Give every helper container and compose fixture a Molecule scenario starts the same cap_drop and no-new-privileges defaults as a service, with only the capabilities its process needs, and add a check that a new one cannot omit them. |
| [`network-boundary-checks.md`](projects/network-boundary-checks.md) | — | Not started | waiting on [ADR-0094/0 (Network boundary checks)](decisions/0094-showing-the-network-boundary-behaves-as-declared/revision-000.md) | A flow list, a probe runner and a canary VM per zone that show the firewall allows the declared flows between zones and blocks the rest, shared by the gateway, coding-agent and operator-host projects. |
| [`openbao-auto-unseal.md`](projects/openbao-auto-unseal.md) | — | Not started | waiting on [ADR-0018/1 (Secrets store unsealing)](decisions/0018-unsealing-the-secrets-store-after-restart/revision-001.md) | Seal OpenBao with an OCI KMS key so a reboot of `security` needs no operator, and let the maintenance job reboot that host again. |
| [`reliance-declaration.md`](projects/reliance-declaration.md) | — | Not started | — | A declared reliance between decisions, checked as a warning that names every approved or accepted revision whose boundary still rests on a working one, as ADR 0080 decides. |
| [`tofu-plan-guard.md`](projects/tofu-plan-guard.md) | — | Not started | waiting on [ADR-0102/0 (Tofu change review)](decisions/0102-knowing-what-a-tofu-change-will-do/revision-000.md) | Build the guard that checks a saved Tofu plan against a committed allow-list of destructive actions, the wrapper that applies the checked plan, and the pull request check that fails an address removed without one, then accept the decision. |
| [`watch-all-rotation-credentials.md`](projects/watch-all-rotation-credentials.md) | — | Not started | — | Make the OpenBao read-watcher alert on a read of the B2 and OCI rotation secrets as well as R2's, as ADR 0026 revision 1 decides. |

## Decisions awaiting a project

| ADR | Problem | Current solution | Status |
| :--- | :--- | :--- | :--- |
| [0003](decisions/0003-certificate-issuance-for-proxied-apps/revision-001.md) | **Certificate issuance for proxied apps** — How Caddy-proxied apps get TLS certificates, and whether each app hostname is exposed in public Certificate Transparency logs. | Proposed revision 1: One wildcard certificate per host with no exception, including tinyauth's own lab domain | Working (proposed revision 1) |
| [0008](decisions/0008-internal-certificate-lifetime/revision-001.md) | **Internal certificate lifetime** — How long certificates from the internal CA live, given the renewal automation that exists. | Proposed revision 1: Shorten the default claim duration toward step-ca's own 24h now that renewal is automated | Working (proposed revision 1) |
| [0038](decisions/0038-iac-misconfiguration-scanning/revision-000.md) | **IaC misconfiguration scanning** — Which scanner checks Ansible and OpenTofu for misconfiguration, without a separate migration for each. | Trivy for Ansible now; Checkov once OpenTofu code lands, then covering both | Working |
| [0041](decisions/0041-testing-the-oci-classic-iam-bootstrap/revision-000.md) | **Testing the OCI classic-IAM bootstrap** — How the OCI classic-IAM bootstrap code is tested beyond hand-written mocks. | floci-oci for the classic-IAM surface only; SCIM tests stay hand-mocked | Working |
| [0045](decisions/0045-security-event-collection-and-alerting/revision-000.md) | **Security event collection and alerting** — Whether purpose-built alerting scripts give way to a security-event pipeline, and where it runs. | Leaning: Wazuh on a dedicated OCI Ampere instance, replacing single-purpose alerting scripts | Working |
| [0096](decisions/0096-knowing-the-pre-commit-hooks-that-run-are-the-reviewed-ones/revision-000.md) | **Knowing the pre-commit hooks that run are the ones that were reviewed** — How the pre-commit hook code and the images hooks pull are made to be the ones a commit names, so they change only in a pull request that shows the change. | Each hook repository is pinned to a full commit SHA with its tag in a comment, each docker hook's image is pinned by digest in the config, and Renovate moves both in a reviewed pull request | Working |
| [0103](decisions/0103-where-tofus-state-is-held/revision-000.md) | **Where Tofu's state is held** — Where OpenTofu's state lives so that the record of what Tofu built depends on neither one machine nor a machine Tofu builds. | An encrypted state bucket in the R2 and B2 accounts the lab already uses, with a credential of its own, one provider live and the other holding a write-only copy | Working |

## Open explorations

| Exploration | Question | Last changed |
| :--- | :--- | :--- |
| [`intrusion-detection-scope.md`](explorations/intrusion-detection-scope.md) | Where should intrusion detection run, and how much of the lab should it see? | 2026-11-07 |
| [`molecule-runtime-without-host-privilege.md`](explorations/molecule-runtime-without-host-privilege.md) | Which container runtime can run the Molecule scenarios on the coding-agent host without giving the agent root there? | 2026-11-07 |
| [`second-cloud-archive-window.md`](explorations/second-cloud-archive-window.md) | Can a second cloud hold the game-world archive for a short window of its own? | 2026-11-07 |
