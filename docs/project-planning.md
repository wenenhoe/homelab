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
| [`cd-agent-approles.md`](projects/cd-agent-approles.md) | 1 | Building | The CD agent's four CIDR-bound AppRoles, and the delivery and rotation of each job's credentials. |
| [`tofu-migration.md`](projects/tofu-migration.md) | 1 | Building | Build the isolated 5XX block and run the first restore.yaml against it, then rebuild on the real VMID ranges, cut over, and decommission the old VMs. |
| [`cd-agent-job-ssh-keys.md`](projects/cd-agent-job-ssh-keys.md) | — | Building | Chained jobs on the CD agent, the monthly leaf-credential rotation that uses them, and the per-job SSH key that its redeploy needs. |
| [`monitoring-host-isolation.md`](projects/monitoring-host-isolation.md) | — | Building | Bring VM 202 under management and move Beszel/Gatus onto a dedicated on-prem host. |
| [`production-and-work-in-progress-branches.md`](projects/production-and-work-in-progress-branches.md) | — | Building | Three long-lived branches where only main is deployed, a promotion checklist on pull requests into main, and Renovate's branch realigned before each run. |
| [`coding-agent-network.md`](projects/coding-agent-network.md) | 6 | De-risking | A dedicated VLAN, default-deny firewall policy and laptop-only Tailscale route for the coding-agent host, after the spikes that settle ADR 0053's assumptions. |
| [`operator-host.md`](projects/operator-host.md) | 2 | De-risking | A headless VM in VLAN 30, reachable only from the maintainer's laptop, with its network rules, tailnet route and hardened baseline, ready to take the controller. |
| [`gcp-e2-micro-provisioning.md`](projects/gcp-e2-micro-provisioning.md) | 1 | De-risking | Onboard a GCP project and define the off-site e2-micro in OpenTofu, with a provisioning identity that leaves no standing key on the host. |
| [`opnsense-config.md`](projects/opnsense-config.md) | — | De-risking | The OPNsense gateway's policy, NAT, DNS forwards and DHCP brought under Ansible through its API from a minimal seed, then the coding-agent zone and its proxy. |
| [`compose-restart-on-changed-mount.md`](projects/compose-restart-on-changed-mount.md) | 1 | Not started — ready | The compose role restarts a container when a file bind-mounted into it changes, and nothing else. |
| [`beszel-agent-docker-api-rules.md`](projects/beszel-agent-docker-api-rules.md) | — | Not started — ready | Replace the beszel-agent proxy's CONTAINERS=1 flag with a rules file naming the calls the pinned agent makes, delivered to the host and tried against the proxy image. |
| [`tailnet-policy-baseline.md`](projects/tailnet-policy-baseline.md) | — | Not started — ready | Replace the tailnet's allow-all policy with explicit grants and tests, once, so the projects that add a route only add a grant. |
| [`workstation-management.md`](projects/workstation-management.md) | — | Not started — ready | Set up the maintainer's laptop as the workstation with WSL2 under a memory cap, a hardware-backed operator-host key, a credential audit, and no desktop assistant with local tool access, then remove every infrastructure credential from VM 401 and retire it. |

## Super Projects

| Initiative | Track | Phase | Project | Unblocks | Status |
| :--- | :--- | :--- | :--- | ---: | :--- |
| `coding-agent-host` | `boundary` | `1-network` | [`coding-agent-network.md`](projects/coding-agent-network.md) | 6 | De-risking |
| | `boundary` | `2-host` | [`coding-agent-host.md`](projects/coding-agent-host.md) | 4 | Not started — waiting on [`coding-agent-network.md`](projects/coding-agent-network.md) |
| | `egress` | — | [`coding-agent-egress.md`](projects/coding-agent-egress.md) | — | Not started — waiting on [`coding-agent-network.md`](projects/coding-agent-network.md) |
| | `lifecycle` | — | [`coding-agent-management.md`](projects/coding-agent-management.md) | — | Not started — waiting on [`cd-agent.md`](projects/cd-agent.md), [`coding-agent-host.md`](projects/coding-agent-host.md) |
| | `workflow` | `1-access-path` | [`coding-agent-access-path.md`](projects/coding-agent-access-path.md) | — | Not started — waiting on [`coding-agent-host.md`](projects/coding-agent-host.md) |
| | `workflow` | `2-molecule-runtime` | [`coding-agent-molecule-runtime.md`](projects/coding-agent-molecule-runtime.md) | — | Not started — waiting on [`coding-agent-host.md`](projects/coding-agent-host.md) |
| `controller-separation` | `operator` | — | [`operator-host.md`](projects/operator-host.md) | 2 | De-risking |
| | `operator` | — | [`operator-host-takeover.md`](projects/operator-host-takeover.md) | — | Not started — waiting on [`operator-host.md`](projects/operator-host.md) |
| | `workstation` | — | [`workstation-management.md`](projects/workstation-management.md) | — | Not started — ready |
| `off-site-monitoring` | `monitoring` | `1-on-prem` | [`monitoring-host-isolation.md`](projects/monitoring-host-isolation.md) | — | Building |
| | `monitoring` | `2-off-site` | [`gcp-e2-micro-provisioning.md`](projects/gcp-e2-micro-provisioning.md) | 1 | De-risking |
| | `monitoring` | `2-off-site` | [`off-site-monitoring.md`](projects/off-site-monitoring.md) | — | De-risking — blocked: no production credential goes to the GCP host until its hardening pass is scoped and done — waiting on [`gcp-e2-micro-provisioning.md`](projects/gcp-e2-micro-provisioning.md) |
| `pull-based-cd` | `agent` | — | [`cd-agent-job-ssh-keys.md`](projects/cd-agent-job-ssh-keys.md) | — | Building |
| | `agent` | — | [`cd-agent.md`](projects/cd-agent.md) | 3 | Building |
| | `credentials` | — | [`cd-agent-approles.md`](projects/cd-agent-approles.md) | 1 | Building |
| | `credentials` | — | [`cd-agent-controller-approle-retirement.md`](projects/cd-agent-controller-approle-retirement.md) | — | Not started — waiting on [`cd-agent.md`](projects/cd-agent.md), [`cd-agent-approles.md`](projects/cd-agent-approles.md) |
| `tofu-vm-provisioning` | `migration` | — | [`tofu-migration.md`](projects/tofu-migration.md) | 1 | Building |
| | `opnsense` | — | [`opnsense-config.md`](projects/opnsense-config.md) | — | De-risking |
| | `windows` | — | [`windows-vms.md`](projects/windows-vms.md) | — | Not started — waiting on [ADR-0092/0](decisions/0092-how-windows-virtual-machines-are-built/revision-000.md) |
| | `dns` | — | [`tofu-vm-dns.md`](projects/tofu-vm-dns.md) | — | De-risking — waiting on [`tofu-migration.md`](projects/tofu-migration.md) |

## Projects

| Project | Unblocks | Status | Covers |
| :--- | ---: | :--- | :--- |
| [`backup-agent-compose-app.md`](projects/backup-agent-compose-app.md) | — | Not started — waiting on [ADR-0088/0](decisions/0088-where-a-role-deployed-stack-compose-file-lives/revision-000.md) | Move the backup agent's compose file under docker/, declare the agent in each backup host's compose_apps, and deploy it through the compose role as a self-managed app. |
| [`beszel-agent-docker-api-rules.md`](projects/beszel-agent-docker-api-rules.md) | — | Not started — ready | Replace the beszel-agent proxy's CONTAINERS=1 flag with a rules file naming the calls the pinned agent makes, delivered to the host and tried against the proxy image. |
| [`bind-mounted-config-files.md`](projects/bind-mounted-config-files.md) | — | Not started — waiting on [`compose-restart-on-changed-mount.md`](projects/compose-restart-on-changed-mount.md) | Mount files Ansible renders read-only from the stack directory, so a config file no longer needs a volume of its own. |
| [`compose-restart-on-changed-mount.md`](projects/compose-restart-on-changed-mount.md) | 1 | Not started — ready | The compose role restarts a container when a file bind-mounted into it changes, and nothing else. |
| [`host-hardening-remaining-hosts.md`](projects/host-hardening-remaining-hosts.md) | — | Not started — waiting on [`operator-host.md`](projects/operator-host.md), [`cd-agent.md`](projects/cd-agent.md), [`coding-agent-host.md`](projects/coding-agent-host.md) | Confirm the operator host, the CD agent, and the coding-agent host include the hardening baseline from their own builds, then settle ADR 0043. |
| [`kms-image.md`](projects/kms-image.md) | — | Not started — waiting on [ADR-0091/0](decisions/0091-where-the-activation-hosts-image-comes-from/revision-000.md) | Build the Windows activation host's server-only image from the upstream py-kms in this repository, attest it, and replace the 11notes images and the kms-gui app. |
| [`licence-check.md`](projects/licence-check.md) | — | Not started — waiting on [ADR-0090/0](decisions/0090-licences-of-adopted-software/revision-000.md) | A registry of every pinned dependency's licence, a check when a pin changes, and a weekly check of each upstream's default-branch licence file, as ADR 0090 decides. |
| [`production-and-work-in-progress-branches.md`](projects/production-and-work-in-progress-branches.md) | — | Building | Three long-lived branches where only main is deployed, a promotion checklist on pull requests into main, and Renovate's branch realigned before each run. |
| [`proxmox-node-install.md`](projects/proxmox-node-install.md) | — | Not started — waiting on [ADR-0093/0](decisions/0093-how-the-proxmox-node-is-installed-and-configured/revision-000.md) | The Proxmox node reinstalled from an ISO with an embedded answer file and brought to the state OpenTofu needs by an idempotent Ansible role, tested on a nested Proxmox VM. |
| [`tailnet-policy-baseline.md`](projects/tailnet-policy-baseline.md) | — | Not started — ready | Replace the tailnet's allow-all policy with explicit grants and tests, once, so the projects that add a route only add a grant. |

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
| [0059](decisions/0059-where-the-tailnet-policy-is-defined/revision-000.md) | **Where the tailnet policy is defined** — The tailnet ACL policy is a security boundary ADRs 0049, 0053, and 0058 depend on; decide where it is authored and when that changes. | Hand-edited in the console now, with tests as the guard; moves to OpenTofu via the tailscale/tailscale provider once ADR 0048's credentials file exists | Working |
| [0079](decisions/0079-knowing-a-backup-archive-came-from-its-host/revision-000.md) | **Knowing a backup archive came from its host** — How a restore shows that the archive it is about to apply was written by the host it claims to be from, whoever else can write to the places archives are kept. | A detached signature per archive from a per-host key, checked at restore against public keys pinned in the repository | Working |
| [0080](decisions/0080-approved-decisions-resting-on-unfinished-ones/revision-000.md) | **Approved decisions that rest on unfinished ones** — How an approved decision's dependence on a decision that is still being worked out is recorded and surfaced, so the boundary it presupposes cannot change unnoticed. | A declared reliance between decisions, checked as a warning that names every approved or accepted revision whose boundary still rests on a working one | Working |
| [0081](decisions/0081-protecting-on-site-backup-archives-from-their-writer/revision-000.md) | **Protecting on-site backup archives from the host that wrote them** — How an archive on `storage` survives a delete requested by the host that wrote it, and how the bucket still shrinks back to its retention window afterwards. | Object Lock in compliance mode on the backup bucket, with lifecycle rules run by an admin and worker beside SeaweedFS removing superseded versions once their lock ends | Working |
