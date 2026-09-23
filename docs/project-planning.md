# Project Planning

Three generated, cross-cutting views; none is a rules doc. For what a
project is and its lifecycle, see [`projects/README.md`](projects/README.md);
for what an ADR is and its revision states, see
[`decisions/README.md`](decisions/README.md).

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
[ADR 0037 revision 1](decisions/0037-decision-and-project-documentation-workflow/revision-001.md)
for why those two fields specifically. A row here isn't automatically a
gap: some are correctly undecided and can't have a project yet, some
are single-PR-sized and don't need one, and this table can't see a
project that references the lineage only in prose without either field
set. It narrows where to look; it doesn't replace looking.

## Super Projects

| Initiative | Track | Phase | Project | Status |
| :--- | :--- | :--- | :--- | :--- |
| `coding-agent-host` | `boundary` | `1-network` | [`coding-agent-network.md`](projects/coding-agent-network.md) | De-risking |
| | `boundary` | `2-host` | [`coding-agent-host.md`](projects/coding-agent-host.md) | Not started — waiting on [`coding-agent-network.md`](projects/coding-agent-network.md) |
| | `boundary` | `3-network-as-code` | [`coding-agent-network-as-code.md`](projects/coding-agent-network-as-code.md) | Not started — waiting on [`tofu-opnsense-day-2.md`](projects/tofu-opnsense-day-2.md), [`coding-agent-network.md`](projects/coding-agent-network.md) |
| | `lifecycle` | — | [`coding-agent-management.md`](projects/coding-agent-management.md) | Not started — waiting on [`tofu-vm-provisioning.md`](projects/tofu-vm-provisioning.md), [`cd-agent.md`](projects/cd-agent.md), [`coding-agent-host.md`](projects/coding-agent-host.md) |
| | `workflow` | `1-access-path` | [`coding-agent-access-path.md`](projects/coding-agent-access-path.md) | Not started — waiting on [`coding-agent-host.md`](projects/coding-agent-host.md), [`workstation-management.md`](projects/workstation-management.md) |
| | `workflow` | `2-molecule-runtime` | [`coding-agent-molecule-runtime.md`](projects/coding-agent-molecule-runtime.md) | Not started — waiting on [`coding-agent-host.md`](projects/coding-agent-host.md) |
| `controller-separation` | `operator` | — | [`operator-host.md`](projects/operator-host.md) | De-risking |
| | `workstation` | `1-management` | [`workstation-management.md`](projects/workstation-management.md) | Not started — waiting on [`operator-host.md`](projects/operator-host.md) |
| | `workstation` | `2-reduction` | [`workstation-capability-reduction.md`](projects/workstation-capability-reduction.md) | Not started — waiting on [`operator-host.md`](projects/operator-host.md), [`workstation-management.md`](projects/workstation-management.md) |
| `off-site-monitoring` | `monitoring` | `1-on-prem` | [`monitoring-host-isolation.md`](projects/monitoring-host-isolation.md) | Building |
| | `monitoring` | `2-off-site` | [`off-site-monitoring.md`](projects/off-site-monitoring.md) | De-risking — blocked: no production credential goes to the GCP host until ADR 0047 is approved, and its hardening pass is unscoped |
| `pull-based-cd` | `agent` | — | [`cd-agent.md`](projects/cd-agent.md) | De-risking |
| | `credentials` | — | [`cd-agent-approles.md`](projects/cd-agent-approles.md) | De-risking |
| | `credentials` | — | [`cd-agent-controller-approle-retirement.md`](projects/cd-agent-controller-approle-retirement.md) | Not started — waiting on [`cd-agent.md`](projects/cd-agent.md), [`cd-agent-approles.md`](projects/cd-agent-approles.md) |
| `security-review-pipeline` | — | — | [`coderabbit-pr-scope-trim.md`](projects/coderabbit-pr-scope-trim.md) | Not started |
| | — | — | [`security-findings-repo.md`](projects/security-findings-repo.md) | Not started |
| | — | — | [`agent-full-repo-audit.md`](projects/agent-full-repo-audit.md) | Not started — waiting on [`security-findings-repo.md`](projects/security-findings-repo.md) |
| | — | — | [`coderabbit-pr-review-pipeline.md`](projects/coderabbit-pr-review-pipeline.md) | Not started — waiting on [`security-findings-repo.md`](projects/security-findings-repo.md), [`coderabbit-pr-scope-trim.md`](projects/coderabbit-pr-scope-trim.md) |
| `tofu-vm-provisioning` | `provisioning` | — | [`tofu-vm-provisioning.md`](projects/tofu-vm-provisioning.md) | De-risking |
| | `migration` | `1-rehearsal` | [`tofu-migration-rehearsal.md`](projects/tofu-migration-rehearsal.md) | Not started — waiting on [`tofu-vm-provisioning.md`](projects/tofu-vm-provisioning.md) |
| | `migration` | `2-cutover` | [`tofu-migration-cutover.md`](projects/tofu-migration-cutover.md) | Not started — waiting on [`tofu-migration-rehearsal.md`](projects/tofu-migration-rehearsal.md) |
| | `opnsense` | — | [`tofu-opnsense-day-2.md`](projects/tofu-opnsense-day-2.md) | De-risking — waiting on [`tofu-migration-cutover.md`](projects/tofu-migration-cutover.md) |

## Projects

| Project | Status | Covers |
| :--- | :--- | :--- |
| [`cloud-credentials-hardening.md`](projects/cloud-credentials-hardening.md) | De-risking | Selective official-SDK adoption for tools/cloud_credentials, and verify.py's rclone calls to boto3. |

## Decisions awaiting a project

| ADR | Problem | Current solution | Status |
| :--- | :--- | :--- | :--- |
| [0003](decisions/0003-certificate-issuance-for-proxied-apps/revision-001.md) | **Certificate issuance for proxied apps** — How Caddy-proxied apps get TLS certificates, and whether each app hostname is exposed in public Certificate Transparency logs. | Proposed revision 1: One wildcard certificate per host with no exception, including tinyauth's own lab domain | Working (proposed revision 1) |
| [0008](decisions/0008-internal-certificate-lifetime/revision-001.md) | **Internal certificate lifetime** — How long certificates from the internal CA live, given the renewal automation that exists. | Proposed revision 1: Shorten the default claim duration toward step-ca's own 24h now that renewal is automated | Working (proposed revision 1) |
| [0038](decisions/0038-iac-misconfiguration-scanning/revision-000.md) | **IaC misconfiguration scanning** — Which scanner checks Ansible and OpenTofu for misconfiguration, without a separate migration for each. | Trivy for Ansible now; Checkov once OpenTofu code lands, then covering both | Working |
| [0039](decisions/0039-intrusion-detection-scope/revision-000.md) | **Intrusion detection scope** — Whether detection lives only on the OPNsense perimeter or also on each VM, without inspecting the lab's own TLS. | Undecided: CrowdSec at the perimeter only, or with per-VM agents | Working |
| [0041](decisions/0041-testing-the-oci-classic-iam-bootstrap/revision-000.md) | **Testing the OCI classic-IAM bootstrap** — How the OCI classic-IAM bootstrap code is tested beyond hand-written mocks. | floci-oci for the classic-IAM surface only; SCIM tests stay hand-mocked | Working |
| [0043](decisions/0043-host-os-hardening-baseline/revision-000.md) | **Host OS hardening baseline** — A deliberate host-level hardening pass (SSH, sysctl, auditd, mandatory access control), not only per-component least privilege. | Undecided: a third-party baseline, or a hand-picked subset in this repo's own roles | Working |
| [0044](decisions/0044-prod-automation-trigger-and-execution/revision-000-a.md) | **Trigger and execution of prod-touching automation** — How deploys and rotations that touch prod are triggered and run, without GitHub dispatching a job to a prod-reaching host. | Undecided between: (000-a) A pull-based CD agent polling origin/main, not a GitHub-dispatched runner; or (000-b) A private, LAN-only Gitea or Forgejo instance with Actions and a runner on the agent host | Working (000-a), Working (000-b) |
| [0045](decisions/0045-security-event-collection-and-alerting/revision-000.md) | **Security event collection and alerting** — Whether purpose-built alerting scripts give way to a security-event pipeline, and where it runs. | Leaning: Wazuh on a dedicated OCI Ampere instance, replacing single-purpose alerting scripts | Working |
| [0059](decisions/0059-where-the-tailnet-policy-is-defined/revision-000.md) | **Where the tailnet policy is defined** — The tailnet ACL policy is a security boundary ADRs 0049, 0053, and 0058 depend on; decide where it is authored and when that changes. | Hand-edited in the console now, with tests as the guard; moves to OpenTofu via the tailscale/tailscale provider once ADR 0048 settles where Tofu's own credentials live | Working |
