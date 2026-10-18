# Project Planning

Four generated, cross-cutting views; none is a rules doc. For what a
project is and its lifecycle, see [`projects/README.md`](projects/README.md);
for what an ADR is and its revision states, see
[`decisions/README.md`](decisions/README.md).

**Next up** lists the projects that can be worked on now: not done, not
blocked, waiting on no existing project, and, if not started, ready.
Building projects come first, so started work finishes before new work
opens, then de-risking ones, then ready ones; within each, the project
with more waiting behind it comes first, then the file name. It orders
what can be started and ranks nothing by importance: no field stores a
priority, per
[ADR 0082 (Choosing the next project)](decisions/0082-choosing-which-project-to-take-up-next/revision-000.md).
A not-started project whose decision is still being worked out is not
listed, since it is not ready; in the other tables its status names the
decision revision it is waiting on.

**Unblocks**, in every table of projects, is the number of existing
projects that wait on that one, directly or through a chain of
`depends_on`; `—` means none does. It counts projects, not effort or
urgency.

**Super Projects** groups every project that belongs to one
(`super_project:` is set) by build order — tracks by their earliest
project in the dependency chain, then phases by slug, then projects by
dependency depth, per
[`projects/README.md`'s Hierarchy section](projects/README.md#hierarchy).
A repeated initiative name is blanked after its first row so the table
reads as one block per initiative.

**Projects** is every project with no `super_project` — the complement
of the view above, in the same shape as
[`projects/README.md`'s own Index](projects/README.md#index), filtered
down to the ones not part of any initiative.

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

## Next up

| Project | Unblocks | Status | Covers |
| :--- | ---: | :--- | :--- |
| [`cd-agent.md`](projects/cd-agent.md) | 3 | Building | A dedicated, pull-based automation host that runs the deploy, maintenance, and freshness jobs. |
| [`cd-agent-approles.md`](projects/cd-agent-approles.md) | 2 | Building | Four CIDR-bound AppRoles for the CD agent (deploy, rotation, freshness and snapshot). |
| [`cd-agent-rotation.md`](projects/cd-agent-rotation.md) | — | Building | Chained jobs on the CD agent, and the monthly leaf-credential rotation that uses them. |
| [`monitoring-host-isolation.md`](projects/monitoring-host-isolation.md) | — | Building | Bring VM 202 under management and move Beszel/Kuma onto a dedicated on-prem host. |
| [`production-and-work-in-progress-branches.md`](projects/production-and-work-in-progress-branches.md) | — | Building | Three long-lived branches where only main is deployed, a promotion checklist on pull requests into main, and Renovate's branch realigned before each run. |
| [`coding-agent-network.md`](projects/coding-agent-network.md) | 6 | De-risking | A dedicated VLAN, default-deny firewall policy, filtering egress proxy, and canary probes for the coding-agent host. |
| [`tofu-vm-provisioning.md`](projects/tofu-vm-provisioning.md) | 5 | De-risking | Tofu skeleton, Ubuntu and OPNsense modules, and the Tofu-to-Ansible inventory generator. |
| [`operator-host.md`](projects/operator-host.md) | 2 | De-risking | A headless VM in VLAN 30, reachable only from the maintainer's laptop, that takes over the controller's tooling and credentials. |
| [`gcp-e2-micro-provisioning.md`](projects/gcp-e2-micro-provisioning.md) | 1 | De-risking | Onboard a GCP project and define the off-site e2-micro in OpenTofu, with a provisioning identity that leaves no standing key on the host. |
| [`workstation-management.md`](projects/workstation-management.md) | 1 | Not started — ready | Set up the maintainer's laptop as the workstation with WSL2 under a memory cap, a hardware-backed operator-host key, a credential audit, and no desktop assistant with local tool access. |
| [`beszel-agent-docker-api-rules.md`](projects/beszel-agent-docker-api-rules.md) | — | Not started — ready | Replace the beszel-agent proxy's CONTAINERS=1 flag with a rules file naming the calls the pinned agent makes, delivered to the host and tried against the proxy image. |
| [`gatus-job-heartbeats.md`](projects/gatus-job-heartbeats.md) | — | Not started — ready | Replace Uptime Kuma push monitors with Gatus external endpoints: one declared endpoint and generated token per job. |

## Super Projects

| Initiative | Track | Phase | Project | Unblocks | Status |
| :--- | :--- | :--- | :--- | ---: | :--- |
| `coding-agent-host` | `boundary` | `1-network` | [`coding-agent-network.md`](projects/coding-agent-network.md) | 6 | De-risking |
| | `boundary` | `2-host` | [`coding-agent-host.md`](projects/coding-agent-host.md) | 4 | Not started — waiting on [`coding-agent-network.md`](projects/coding-agent-network.md) |
| | `boundary` | `3-network-as-code` | [`coding-agent-network-as-code.md`](projects/coding-agent-network-as-code.md) | — | Not started — waiting on [`tofu-opnsense-day-2.md`](projects/tofu-opnsense-day-2.md), [`coding-agent-network.md`](projects/coding-agent-network.md) |
| | `lifecycle` | — | [`coding-agent-management.md`](projects/coding-agent-management.md) | — | Not started — waiting on [`tofu-vm-provisioning.md`](projects/tofu-vm-provisioning.md), [`cd-agent.md`](projects/cd-agent.md), [`coding-agent-host.md`](projects/coding-agent-host.md) |
| | `workflow` | `1-access-path` | [`coding-agent-access-path.md`](projects/coding-agent-access-path.md) | — | Not started — waiting on [`coding-agent-host.md`](projects/coding-agent-host.md) |
| | `workflow` | `2-molecule-runtime` | [`coding-agent-molecule-runtime.md`](projects/coding-agent-molecule-runtime.md) | — | Not started — waiting on [`coding-agent-host.md`](projects/coding-agent-host.md) |
| `controller-separation` | `operator` | — | [`operator-host.md`](projects/operator-host.md) | 2 | De-risking |
| | `workstation` | `1-management` | [`workstation-management.md`](projects/workstation-management.md) | 1 | Not started — ready |
| | `workstation` | `2-reduction` | [`workstation-capability-reduction.md`](projects/workstation-capability-reduction.md) | — | Not started — waiting on [`operator-host.md`](projects/operator-host.md), [`workstation-management.md`](projects/workstation-management.md) |
| `off-site-monitoring` | `monitoring` | `1-on-prem` | [`monitoring-host-isolation.md`](projects/monitoring-host-isolation.md) | — | Building |
| | `monitoring` | `2-off-site` | [`gcp-e2-micro-provisioning.md`](projects/gcp-e2-micro-provisioning.md) | 1 | De-risking |
| | `monitoring` | `2-off-site` | [`off-site-monitoring.md`](projects/off-site-monitoring.md) | — | De-risking — blocked: no production credential goes to the GCP host until its hardening pass is scoped and done — waiting on [`gcp-e2-micro-provisioning.md`](projects/gcp-e2-micro-provisioning.md) |
| `pull-based-cd` | `agent` | — | [`cd-agent-job-ssh-keys.md`](projects/cd-agent-job-ssh-keys.md) | — | Not started — waiting on [ADR-0075/0](decisions/0075-giving-an-automation-job-its-own-ssh-identity/revision-000.md) |
| | `agent` | — | [`cd-agent-rotation.md`](projects/cd-agent-rotation.md) | — | Building |
| | `agent` | — | [`cd-agent.md`](projects/cd-agent.md) | 3 | Building |
| | `credentials` | — | [`cd-agent-approles.md`](projects/cd-agent-approles.md) | 2 | Building |
| | `credentials` | — | [`cd-agent-controller-approle-retirement.md`](projects/cd-agent-controller-approle-retirement.md) | — | Not started — waiting on [`cd-agent.md`](projects/cd-agent.md), [`cd-agent-approles.md`](projects/cd-agent-approles.md) |
| | `credentials` | — | [`cd-agent-credential-delivery.md`](projects/cd-agent-credential-delivery.md) | — | Not started — waiting on [`cd-agent-approles.md`](projects/cd-agent-approles.md) |
| `tofu-vm-provisioning` | `provisioning` | — | [`tofu-vm-provisioning.md`](projects/tofu-vm-provisioning.md) | 5 | De-risking |
| | `migration` | `1-rehearsal` | [`tofu-migration-rehearsal.md`](projects/tofu-migration-rehearsal.md) | 3 | Not started — waiting on [`tofu-vm-provisioning.md`](projects/tofu-vm-provisioning.md) |
| | `migration` | `2-cutover` | [`tofu-migration-cutover.md`](projects/tofu-migration-cutover.md) | 2 | Not started — waiting on [`tofu-migration-rehearsal.md`](projects/tofu-migration-rehearsal.md) |
| | `opnsense` | — | [`tofu-opnsense-day-2.md`](projects/tofu-opnsense-day-2.md) | 1 | De-risking — waiting on [`tofu-migration-cutover.md`](projects/tofu-migration-cutover.md) |

## Projects

| Project | Unblocks | Status | Covers |
| :--- | ---: | :--- | :--- |
| [`beszel-agent-docker-api-rules.md`](projects/beszel-agent-docker-api-rules.md) | — | Not started — ready | Replace the beszel-agent proxy's CONTAINERS=1 flag with a rules file naming the calls the pinned agent makes, delivered to the host and tried against the proxy image. |
| [`gatus-job-heartbeats.md`](projects/gatus-job-heartbeats.md) | — | Not started — ready | Replace Uptime Kuma push monitors with Gatus external endpoints: one declared endpoint and generated token per job. |
| [`host-hardening-remaining-hosts.md`](projects/host-hardening-remaining-hosts.md) | — | Not started — waiting on [`operator-host.md`](projects/operator-host.md), [`cd-agent.md`](projects/cd-agent.md), [`coding-agent-host.md`](projects/coding-agent-host.md) | Confirm the operator host, the CD agent, and the coding-agent host include the hardening baseline from their own builds, then settle ADR 0043. |
| [`production-and-work-in-progress-branches.md`](projects/production-and-work-in-progress-branches.md) | — | Building | Three long-lived branches where only main is deployed, a promotion checklist on pull requests into main, and Renovate's branch realigned before each run. |

## Decisions awaiting a project

| ADR | Problem | Current solution | Status |
| :--- | :--- | :--- | :--- |
| [0026](decisions/0026-detecting-reads-of-high-value-secrets/revision-001.md) | **Detecting reads of high-value secrets** — Every read of the R2 admin token's path is visible and raises an alert. | Proposed revision 1: Match request lines and watch every secret-bearing rotation credential, not only R2's | Approved (proposed revision 1) |
| [0003](decisions/0003-certificate-issuance-for-proxied-apps/revision-001.md) | **Certificate issuance for proxied apps** — How Caddy-proxied apps get TLS certificates, and whether each app hostname is exposed in public Certificate Transparency logs. | Proposed revision 1: One wildcard certificate per host with no exception, including tinyauth's own lab domain | Working (proposed revision 1) |
| [0008](decisions/0008-internal-certificate-lifetime/revision-001.md) | **Internal certificate lifetime** — How long certificates from the internal CA live, given the renewal automation that exists. | Proposed revision 1: Shorten the default claim duration toward step-ca's own 24h now that renewal is automated | Working (proposed revision 1) |
| [0038](decisions/0038-iac-misconfiguration-scanning/revision-000.md) | **IaC misconfiguration scanning** — Which scanner checks Ansible and OpenTofu for misconfiguration, without a separate migration for each. | Trivy for Ansible now; Checkov once OpenTofu code lands, then covering both | Working |
| [0039](decisions/0039-intrusion-detection-scope/revision-000.md) | **Intrusion detection scope** — Whether detection lives only on the OPNsense perimeter or also on each VM, without inspecting the lab's own TLS. | Undecided: CrowdSec at the perimeter only, or with per-VM agents | Working |
| [0041](decisions/0041-testing-the-oci-classic-iam-bootstrap/revision-000.md) | **Testing the OCI classic-IAM bootstrap** — How the OCI classic-IAM bootstrap code is tested beyond hand-written mocks. | floci-oci for the classic-IAM surface only; SCIM tests stay hand-mocked | Working |
| [0045](decisions/0045-security-event-collection-and-alerting/revision-000.md) | **Security event collection and alerting** — Whether purpose-built alerting scripts give way to a security-event pipeline, and where it runs. | Leaning: Wazuh on a dedicated OCI Ampere instance, replacing single-purpose alerting scripts | Working |
| [0059](decisions/0059-where-the-tailnet-policy-is-defined/revision-000.md) | **Where the tailnet policy is defined** — The tailnet ACL policy is a security boundary ADRs 0049, 0053, and 0058 depend on; decide where it is authored and when that changes. | Hand-edited in the console now, with tests as the guard; moves to OpenTofu via the tailscale/tailscale provider once ADR 0048 settles where Tofu's own credentials live | Working |
| [0079](decisions/0079-knowing-a-backup-archive-came-from-its-host/revision-000.md) | **Knowing a backup archive came from its host** — How a restore shows that the archive it is about to apply was written by the host it claims to be from, whoever else can write to the places archives are kept. | A detached signature per archive from a per-host key, checked at restore against public keys pinned in the repository | Working |
| [0080](decisions/0080-approved-decisions-resting-on-unfinished-ones/revision-000.md) | **Approved decisions that rest on unfinished ones** — How an approved decision's dependence on a decision that is still being worked out is recorded and surfaced, so the boundary it presupposes cannot change unnoticed. | A declared reliance between decisions, checked as a warning that names every approved or accepted revision whose boundary still rests on a working one | Working |
| [0081](decisions/0081-protecting-on-site-backup-archives-from-their-writer/revision-000.md) | **Protecting on-site backup archives from the host that wrote them** — How an archive on `storage` survives a delete requested by the host that wrote it, and how the bucket still shrinks back to its retention window afterwards. | Object Lock in compliance mode on the backup bucket, with lifecycle rules run by an admin and worker beside SeaweedFS removing superseded versions once their lock ends | Working |
| [0087](decisions/0087-delivering-files-ansible-renders-to-a-container/revision-000.md) | **Delivering files that Ansible renders to a container** — Where a file Ansible renders for a container lives, so a config file needs no volume of its own. | Read-only bind mounts from the stack directory; volumes only for state the app writes | Working |
