# Project Planning

Four generated, cross-cutting views; none is a rules doc. For what a
project is and its lifecycle, see [`projects/README.md`](projects/README.md);
for what an ADR is and its revision states, see
[`decisions/README.md`](decisions/README.md); for every ADR by number and
topic, see [`decision-index.md`](decision-index.md).

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

**Covers**, in every table of projects, is the project's `summary:`.

**Super Projects** groups every project that belongs to one
(`super_project:` is set) by build order — projects by dependency depth,
then by file name, per
[`projects/README.md`'s Hierarchy section](projects/README.md#hierarchy).
A repeated initiative name is blanked after its first row so the table
reads as one block per initiative.

**Projects** is every project with no `super_project` — the complement
of the view above, with the same columns. It lists building projects
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

| Initiative | Project | Unblocks | Status | Blocker | Covers |
| :--- | :--- | ---: | :--- | :--- | :--- |
| `backup-archive-protection` | [`backup-archive-retention-lock.md`](projects/backup-archive-retention-lock.md) | — | Not started | waiting on [ADR-0081/0 (On-site archive deletion)](decisions/0081-protecting-on-site-backup-archives-from-their-writer/revision-000.md) | Lock the on-site backup bucket in compliance mode so the host that wrote an archive cannot delete it, and expire superseded versions once their lock ends, as ADR 0081 decides. |
| | [`backup-archive-signing.md`](projects/backup-archive-signing.md) | — | Not started | waiting on [ADR-0079/0 (Backup archive authenticity)](decisions/0079-knowing-a-backup-archive-came-from-its-host/revision-000.md) | Sign each backup archive with a per-host key and make a restore refuse any archive whose signature does not verify against a key pinned in the repository, as ADR 0079 decides. |
| `coding-agent-host` | [`coding-agent-network.md`](projects/coding-agent-network.md) | 6 | Not started | waiting on [ADR-0053/0 (Coding-agent network reach)](decisions/0053-network-reach-of-the-coding-agent-host/revision-000.md) | A dedicated VLAN, default-deny firewall policy and laptop-only Tailscale route for the coding-agent host. |
| | [`coding-agent-egress.md`](projects/coding-agent-egress.md) | 5 | Not started | waiting on [`coding-agent-network.md`](projects/coding-agent-network.md) | A filtering egress proxy for the coding-agent zone and VLAN 30, and canary probes that check the whole boundary from outside the host. |
| | [`coding-agent-host.md`](projects/coding-agent-host.md) | 2 | Not started | waiting on [`coding-agent-network.md`](projects/coding-agent-network.md), [`coding-agent-egress.md`](projects/coding-agent-egress.md) | The dedicated VM, Ansible role, and inventory group that run Claude Code unprivileged under its built-in sandbox. |
| | [`coding-agent-access-path.md`](projects/coding-agent-access-path.md) | — | Not started | waiting on [`coding-agent-host.md`](projects/coding-agent-host.md); rests on ADR-0053 (working) | Terminal-only access to the coding-agent host and the fetch-review-push workflow, so the host never holds or reaches a push credential. |
| | [`coding-agent-management.md`](projects/coding-agent-management.md) | — | Not started | waiting on [`cd-agent.md`](projects/cd-agent.md), [`coding-agent-host.md`](projects/coding-agent-host.md) | Rebuild-first management of the coding-agent host from the Tofu definition at each start, with a dedicated key and a CD-agent job that holds nothing else. |
| `compose-stack-files` | [`backup-agent-compose-app.md`](projects/backup-agent-compose-app.md) | — | Not started | waiting on [ADR-0088/0 (Role-deployed stack compose)](decisions/0088-where-a-role-deployed-stack-compose-file-lives/revision-000.md) | Move the backup agent's compose file under docker/, declare the agent in each backup host's compose_apps, and deploy it through the compose role as a self-managed app. |
| | [`beszel-agent-docker-api-rules.md`](projects/beszel-agent-docker-api-rules.md) | — | Not started | — | Replace the beszel-agent proxy's CONTAINERS=1 flag with a rules file naming the calls the pinned agent makes, delivered to the host and tried against the proxy image. |
| | [`compose-restart-on-changed-mount.md`](projects/compose-restart-on-changed-mount.md) | 1 | Not started | — | The compose role restarts a container when a file bind-mounted into it changes, and nothing else. |
| | [`bind-mounted-config-files.md`](projects/bind-mounted-config-files.md) | — | Not started | waiting on [`compose-restart-on-changed-mount.md`](projects/compose-restart-on-changed-mount.md) | Mount files Ansible renders read-only from the stack directory, so a config file no longer needs a volume of its own. |
| `controller-separation` | [`operator-host.md`](projects/operator-host.md) | 5 | Not started | waiting on [ADR-0058/0 (Operator work host)](decisions/0058-where-operator-work-runs/revision-000.md) | A headless VM in VLAN 30, reachable only from the maintainer's laptop, with its network rules, tailnet route and hardened baseline, ready to take the controller. |
| | [`workstation-management.md`](projects/workstation-management.md) | 1 | Not started | rests on ADR-0058 (working) | Set up the maintainer's laptop as the workstation with WSL2 under a memory cap, a credential audit, and no desktop assistant with local tool access. |
| | [`operator-host-takeover.md`](projects/operator-host-takeover.md) | 1 | Not started | waiting on [`operator-host.md`](projects/operator-host.md), [`coding-agent-egress.md`](projects/coding-agent-egress.md) | The egress allowlist for VLAN 30, then the controller's toolchain and credentials moved onto the operator host. |
| | [`vm-401-retirement.md`](projects/vm-401-retirement.md) | — | Not started | waiting on [`operator-host-takeover.md`](projects/operator-host-takeover.md), [`workstation-management.md`](projects/workstation-management.md); rests on ADR-0058 (working) | Remove every infrastructure credential from VM 401 and destroy it, once the operator host has taken the controller and the laptop is set up as the workstation. |
| `off-site-monitoring` | [`gcp-e2-micro-provisioning.md`](projects/gcp-e2-micro-provisioning.md) | 1 | Not started | waiting on [ADR-0073/0 (Off-site cloud auth)](decisions/0073-how-provisioning-authenticates-to-the-off-site-cloud/revision-000.md) | Onboard a GCP project and define the off-site e2-micro in OpenTofu, with a provisioning identity that leaves no standing key on the host. |
| | [`monitoring-host-isolation.md`](projects/monitoring-host-isolation.md) | — | Building | — | Bring VM 202 under management and move Beszel/Gatus onto a dedicated on-prem host. |
| | [`off-site-monitoring.md`](projects/off-site-monitoring.md) | — | Not started | waiting on [`gcp-e2-micro-provisioning.md`](projects/gcp-e2-micro-provisioning.md) | Relocate monitoring to a GCP e2-micro so it survives loss of the whole site. |
| `pull-based-cd` | [`cd-agent-approles.md`](projects/cd-agent-approles.md) | 1 | Building | — | The CD agent's four CIDR-bound AppRoles, and the delivery and rotation of each job's credentials. |
| | [`cd-agent-job-ssh-keys.md`](projects/cd-agent-job-ssh-keys.md) | — | Building | — | Chained jobs on the CD agent, the monthly leaf-credential rotation that uses them, and the per-job SSH key that its redeploy needs. |
| | [`cd-agent.md`](projects/cd-agent.md) | 2 | Building | waiting on [`operator-host.md`](projects/operator-host.md); rests on ADR-0058 (working), ADR-0053 (working) | A dedicated, pull-based automation host that runs the deploy, maintenance, and credential-expiry jobs. |
| | [`cd-agent-controller-approle-retirement.md`](projects/cd-agent-controller-approle-retirement.md) | — | Not started | waiting on [`cd-agent.md`](projects/cd-agent.md), [`cd-agent-approles.md`](projects/cd-agent-approles.md) | Delete controller's AppRole; admin access mints short-lived tokens on demand. |
| `tofu-vm-provisioning` | [`opnsense-config.md`](projects/opnsense-config.md) | — | Building | rests on ADR-0053 (working) | The OPNsense gateway's policy, NAT, DNS forwards and DHCP brought under Ansible through its API from a minimal seed, then the production gateway rebuilt from it. |
| | [`proxmox-node-install.md`](projects/proxmox-node-install.md) | — | Not started | waiting on [ADR-0093/0 (Proxmox node install)](decisions/0093-how-the-proxmox-node-is-installed-and-configured/revision-000.md) | The Proxmox node reinstalled from an ISO with an embedded answer file and brought to the state OpenTofu needs by an idempotent Ansible role, tested on a nested Proxmox VM. |
| | [`windows-vms.md`](projects/windows-vms.md) | — | Not started | waiting on [ADR-0092/0 (Windows VM builds)](decisions/0092-how-windows-virtual-machines-are-built/revision-000.md) | Windows machines created by OpenTofu from their install media with an unattended answer file rendered in this repository, starting with the desktops and the one with a GPU. |

## Projects

| Project | Unblocks | Status | Blocker | Covers |
| :--- | ---: | :--- | :--- | :--- |
| [`dr-exercises.md`](projects/dr-exercises.md) | — | Building | — | Carry out the disaster-recovery exercise cadence: show each system's recovery tier and drill age in the coverage view, run the first quarter of exercises, and accept the decision. |
| [`network-boundary-checks.md`](projects/network-boundary-checks.md) | — | Building | — | A flow list, a probe runner and a canary VM per zone that show the firewall allows the declared flows between zones and blocks the rest, shared by the gateway, coding-agent and operator-host projects. |
| [`kms-image.md`](projects/kms-image.md) | — | Not started | waiting on [ADR-0091/0 (Activation host image)](decisions/0091-where-the-activation-hosts-image-comes-from/revision-000.md) | Build the Windows activation host's server-only image from the upstream py-kms in this repository, attest it, and replace the 11notes images and the kms-gui app. |
| [`licence-check.md`](projects/licence-check.md) | — | Not started | waiting on [ADR-0090/0 (Adopted software licences)](decisions/0090-licences-of-adopted-software/revision-000.md) | A registry of every pinned dependency's licence, a check when a pin changes, and a weekly check of each upstream's default-branch licence file, as ADR 0090 decides. |
| [`molecule-container-hardening.md`](projects/molecule-container-hardening.md) | — | Not started | — | Give every helper container and compose fixture a Molecule scenario starts the same cap_drop and no-new-privileges defaults as a service, with only the capabilities its process needs, and add a check that a new one cannot omit them, and a check that holds the production compose files and the containers Ansible starts to the same pair. |
| [`openbao-auto-unseal.md`](projects/openbao-auto-unseal.md) | — | Not started | waiting on [ADR-0018/1 (Secrets store unsealing)](decisions/0018-unsealing-the-secrets-store-after-restart/revision-001.md) | Seal OpenBao with an OCI KMS key so a reboot of `security` needs no operator, and let the maintenance job reboot that host again. |
| [`project-start-gate.md`](projects/project-start-gate.md) | — | Not started | — | Make a project start only through a gate of an approved decision, a confirmed plan and a complete scope, keep assumptions in the decision, size projects to close on their own, and review the projects that exist against those rules, as ADR 0037 revision 5 decides. |
| [`tailnet-policy-in-tofu.md`](projects/tailnet-policy-in-tofu.md) | — | Not started | waiting on [ADR-0059/0 (Tailnet policy)](decisions/0059-where-the-tailnet-policy-is-defined/revision-000.md) | Move the tailnet's policy from hand edits in the console to OpenTofu through the tailscale/tailscale provider, with its private values supplied at apply time, as ADR 0059 decides. |
| [`tofu-plan-guard.md`](projects/tofu-plan-guard.md) | — | Not started | waiting on [ADR-0102/0 (Tofu change review)](decisions/0102-knowing-what-a-tofu-change-will-do/revision-000.md) | Build the guard that checks a saved Tofu plan against a committed allow-list of destructive actions, the wrapper that applies the checked plan, and the pull request check that fails an address removed without one, then accept the decision. |

## Decisions awaiting a project

| ADR | Problem | Current solution | Status |
| :--- | :--- | :--- | :--- |
| [0003](decisions/0003-certificate-issuance-for-proxied-apps/revision-001.md) | **Certificate issuance for proxied apps** — How Caddy-proxied apps get TLS certificates, and whether each app hostname is exposed in public Certificate Transparency logs. | Proposed revision 1: One wildcard certificate per host with no exception, including tinyauth's own lab domain | Working (proposed revision 1) |
| [0008](decisions/0008-internal-certificate-lifetime/revision-001.md) | **Internal certificate lifetime** — How long certificates from the internal CA live, given the renewal automation that exists. | Proposed revision 1: Shorten the default claim duration toward step-ca's own 24h now that renewal is automated | Working (proposed revision 1) |
| [0038](decisions/0038-iac-misconfiguration-scanning/revision-000.md) | **IaC misconfiguration scanning** — Which scanner checks Ansible and OpenTofu for misconfiguration, without a separate migration for each. | Trivy for Ansible now; Checkov once OpenTofu code lands, then covering both | Working |
| [0041](decisions/0041-testing-the-oci-classic-iam-bootstrap/revision-000.md) | **Testing the OCI classic-IAM bootstrap** — How the OCI classic-IAM bootstrap code is tested beyond hand-written mocks. | floci-oci for the classic-IAM surface only; SCIM tests stay hand-mocked | Working |
| [0045](decisions/0045-security-event-collection-and-alerting/revision-000.md) | **Security event collection and alerting** — Whether purpose-built alerting scripts give way to a security-event pipeline, and where it runs. | Leaning: Wazuh on a dedicated OCI Ampere instance, replacing single-purpose alerting scripts | Working |
| [0096](decisions/0096-knowing-the-pre-commit-hooks-that-run-are-the-reviewed-ones/revision-000.md) | **Knowing the pre-commit hooks that run are the ones that were reviewed** — How the pre-commit hook code and the images hooks pull are made to be the ones a commit names, so they change only in a pull request that shows the change. | Each hook repository is pinned to a full commit SHA with its tag in a comment, each docker hook's image is pinned by digest in the config, and Renovate moves both in a reviewed pull request | Working |

## Open explorations

| Exploration | Question | Last changed |
| :--- | :--- | :--- |
| [`intrusion-detection-scope.md`](explorations/intrusion-detection-scope.md) | Where should intrusion detection run, and how much of the lab should it see? | 2026-11-07 |
| [`molecule-runtime-without-host-privilege.md`](explorations/molecule-runtime-without-host-privilege.md) | Which container runtime can run the Molecule scenarios on the coding-agent host without giving the agent root there? | 2026-11-07 |
| [`host-alert-declaration.md`](explorations/host-alert-declaration.md) | Where should a host-resource alert be declared so that a rebuilt monitor brings it back? | 2026-11-09 |
| [`host-drift-detection.md`](explorations/host-drift-detection.md) | How could the lab notice that a host no longer matches what `main` declares? | 2026-11-09 |
| [`offsite-lock-settings-check.md`](explorations/offsite-lock-settings-check.md) | How could the lab notice that an off-site bucket's lock or lifecycle setting is gone or shorter than it should be? | 2026-11-10 |
| [`cloud-credential-custody.md`](explorations/cloud-credential-custody.md) | How could the credentials that mint and revoke the cloud keys be kept away from the host that runs the secrets store? | 2026-11-11 |
| [`post-compromise-archive-relay.md`](explorations/post-compromise-archive-relay.md) | How could the lab notice that an archive a compromised host made has been relayed offsite as if it were genuine? | 2026-11-11 |
| [`second-cloud-archive-window.md`](explorations/second-cloud-archive-window.md) | Can a second cloud hold the game-world archive for a short window of its own? | 2026-11-11 |
| [`refactoring-review-lens.md`](explorations/refactoring-review-lens.md) | Can the automated review look for refactoring without producing noise? | 2026-11-12 |
