# Projects

A project is a temporary execution record for multi-stage work: where
the build stands, what remains, and what it waits on. It never owns
rationale (that's an [ADR](../decisions/README.md)) or current behavior
(that's a topic doc), and it is deleted once everything durable has a
home.

Topic docs describe `main` at every commit. A stage that has merged is
current behavior even while its project is unfinished — update the topic
doc in the same PR. The project only tracks what is left.

## When this is the right artifact

A genuinely multi-stage, multi-PR piece of work with a real stage table —
more than one row that isn't "done in this PR." A single-PR feature,
however large, doesn't qualify: it gets a topic doc, or an ADR if it
involved a contested choice. A project needs an ADR only when it
implements a real decision; otherwise it has no `decision:` and nothing
gates it.

## Hierarchy

- **Super-project** — a large initiative that needs several projects. A
  label (`super_project:`), not a document; see [By initiative](#by-initiative).
- **Track** — an independent stream of work within a super-project
  (`track:`).
- **Phase** — an ordered grouping within a track (`phase:`).
- **Project** — the smallest independently manageable and closable unit;
  one doc.
- **Stage** — a sequential build step inside one project. Numbering is
  local to that doc.

A `track` needs a `super_project`, and a `phase` needs a `track`. No
level is required; don't add one for naming's sake. Decompose a broad
initiative top-down, or add a `super_project` label once existing
projects turn out to be coupled — both are fine.

The generated [By initiative](#by-initiative) view reads in build order:
tracks by their earliest project in the dependency chain, then phases by
slug, then projects by dependency depth. Where an order isn't a
dependency (two stages that merely go one after the other), make them
phases of one track and number the slugs (`1-…`, `2-…`); the view can't
infer it.

Hierarchy says where work belongs; dependency says what must finish
first. Declare `depends_on` (`project:` and `reason:`) only when work
here cannot proceed until that project is done — not for relatedness, a
shared ADR, similar subject, or preferred order. The index shows
"waiting on" while the predecessor still exists; remove the entry in the
change that deletes the finished predecessor, or the checker fails on a
dangling one.

## Lifecycle

| Status | Meaning | Linked `decision:` revision must be |
| :--- | :--- | :--- |
| `not-started` | Nothing underway. | `working` or `approved` |
| `de-risking` | Resolving an open assumption — only throwaway spikes or reading code. | `working` |
| `building` | Production implementation is authorized. | `approved` |
| `done` | Everything implemented and merged. | `accepted` |

`check-doc-drift.py` enforces the last column, so a revision that drops
back to `working` stops any project `building` on it. A project without
`decision:` isn't gated.

`blocked: true` with a `blocked_reason` is a flag, not a status: a
current impediment that isn't another project (hardware, an external
service). Waiting on a project is derived from `depends_on`. A risk —
something that could cause rework but blocks nothing now — goes in the
doc's Risks list instead.

## What goes in one

The shape of [`TEMPLATE.md`](TEMPLATE.md): scope, the decision it
implements, a stage table (`Not started` / `In progress` / `Done`, each
with an exit condition), acceptance criteria, agent handoff, risks, and
open items. Update the stage table at the start and end of each PR that
works a stage. If a stage's prose starts explaining why X over Y, stop
and write or extend the ADR instead.

## Stop conditions

Whoever is implementing — human or agent — stops and hands the decision
to a human when:

- implementing needs a change to the linked revision's Decision;
- a new material assumption turns up;
- an acceptance criterion can't be satisfied;
- a new dependency or security boundary appears;
- the scope needs to grow, which includes a file outside `allowed_paths`
  (see [Scope](#scope)).

For the first two, record it (an agent's only permitted ADR edits are in
[`docs/decisions/README.md#assumptions`](../decisions/README.md#assumptions))
and stop; don't improvise around it.

## Scope

A project doc may declare `allowed_paths`: the file globs its work may
change.

```yaml
allowed_paths:
  - .github/scripts/doc_*.py
  - tools/tests/doc_scripts/**
```

`*` and `?` stay inside one directory; `**` crosses directories. A
pattern that matches every file (`**`, `*`) is rejected, since it would
bound nothing.

A change is tied to a project by touching its doc, which any change that
works a stage already does. Every other file that change touches must
match `allowed_paths`, apart from what the workflow itself produces:
project docs, the generated decisions index, and the revision the
project's `decision:` names, so the permitted ADR edits stay possible. A
change that touches no project doc isn't project work and isn't checked.
One that touches several scoped projects gets the union of their scopes.

The scope in force is the one on the base branch, not the one in the
change, so widening `allowed_paths` is its own change, reviewed before it
is used. A project doc that is new in a change has no scope yet.

This is the mechanical half of the "scope needs to grow" stop condition:
work that needs a file outside `allowed_paths` fails the check and stops.
Omit the field for work no agent will touch. It is path-level only: it
can't tell whether an edit inside an allowed file is the permitted one,
and a change that never touches its project doc isn't bounded. How and
where it runs is in
[`docs/ci.md#project-scope-check`](../ci.md#project-scope-check).

## Public repo

Risks, blockers, and any evidence recorded here follow the rule in
[`docs/README.md#public-repo`](../README.md#public-repo): no live
vulnerability, incident, or exposure window.

## When a project finishes

Once every stage is done and everything durable has a home, delete the
doc rather than trimming it to a pointer or archiving it — what's left is
either current-state fact (which belongs in a topic doc) or build
narrative (which git and the PRs already hold). Run the checklist first;
skipping it is how a real fact gets lost instead of promoted.

### Closing checklist

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] The linked revision is `accepted` (set in the PR that completes the
      work), or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc, not only here.
- [ ] Every open item is resolved and promoted, or moved to the ADR or
      project it belongs to next.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.

## Index

| Project | Status | Covers |
| :--- | :--- | :--- |
| [`ansible-collections-audit.md`](ansible-collections-audit.md) | Building | Replace hand-rolled command/shell/uri tasks in ansible/roles/* with maintained collection modules where one fits. |
| [`cd-agent-approles.md`](cd-agent-approles.md) | De-risking | Two CIDR-bound AppRoles for the CD agent (deploy and rotation). |
| [`cd-agent-controller-approle-retirement.md`](cd-agent-controller-approle-retirement.md) | Not started — waiting on [`cd-agent.md`](cd-agent.md), [`cd-agent-approles.md`](cd-agent-approles.md) | Delete controller's Era A AppRole; admin access mints short-lived tokens on demand. |
| [`cd-agent.md`](cd-agent.md) | De-risking | A dedicated, pull-based automation host that runs deploy, maintenance, rotation, and freshness jobs. |
| [`cloud-credentials-hardening.md`](cloud-credentials-hardening.md) | De-risking | Selective official-SDK adoption for tools/cloud_credentials, and verify.py's rclone calls to boto3. |
| [`coding-agent-access-path.md`](coding-agent-access-path.md) | Not started — waiting on [`coding-agent-host.md`](coding-agent-host.md), [`workstation-management.md`](workstation-management.md) | Split maintainer client identities and the fetch-review-push workflow, so the coding-agent host never holds or reaches a push credential. |
| [`coding-agent-host.md`](coding-agent-host.md) | Not started — waiting on [`coding-agent-network.md`](coding-agent-network.md) | The dedicated VM, Ansible role, and inventory group that run Claude Code unprivileged under its built-in sandbox. |
| [`coding-agent-management.md`](coding-agent-management.md) | Not started — waiting on [`tofu-vm-provisioning.md`](tofu-vm-provisioning.md), [`cd-agent.md`](cd-agent.md), [`coding-agent-host.md`](coding-agent-host.md) | Rebuild-first management of the coding-agent host from the Tofu definition, with a dedicated key and a CD-agent job that holds nothing else. |
| [`coding-agent-molecule-runtime.md`](coding-agent-molecule-runtime.md) | Not started — waiting on [`coding-agent-host.md`](coding-agent-host.md) | Choose and adopt a container runtime that runs the repo's privileged, systemd-based Molecule scenarios without host-level root on the coding-agent host. |
| [`coding-agent-network-as-code.md`](coding-agent-network-as-code.md) | Not started — waiting on [`tofu-opnsense-day-2.md`](tofu-opnsense-day-2.md), [`coding-agent-network.md`](coding-agent-network.md) | Move the coding-agent VLAN, firewall rules, and proxy configuration from hand-maintained OPNsense state into Tofu. |
| [`coding-agent-network.md`](coding-agent-network.md) | De-risking | A dedicated VLAN, default-deny firewall policy, filtering egress proxy, and canary probes for the coding-agent host. |
| [`monitoring-host-isolation.md`](monitoring-host-isolation.md) | Building | Bring VM 202 under management and move Beszel/Kuma onto a dedicated on-prem host. |
| [`off-site-monitoring.md`](off-site-monitoring.md) | De-risking — blocked: no production credential goes to the GCP host until ADR 0047 is approved, and its hardening pass is unscoped | Relocate monitoring to a GCP e2-micro so it survives loss of the whole site. |
| [`tofu-migration-cutover.md`](tofu-migration-cutover.md) | Not started — waiting on [`tofu-migration-rehearsal.md`](tofu-migration-rehearsal.md) | Rebuild on the real VMID ranges, cut over, and decommission the old VMs. |
| [`tofu-migration-rehearsal.md`](tofu-migration-rehearsal.md) | Not started — waiting on [`tofu-vm-provisioning.md`](tofu-vm-provisioning.md) | Build the isolated 5XX block and run the first restore.yaml against it. |
| [`tofu-opnsense-day-2.md`](tofu-opnsense-day-2.md) | De-risking — waiting on [`tofu-migration-cutover.md`](tofu-migration-cutover.md) | Kea, VLAN, and static DNS configured through OPNsense's API. |
| [`tofu-vm-provisioning.md`](tofu-vm-provisioning.md) | De-risking | Tofu skeleton, Ubuntu and OPNsense modules, and the Tofu-to-Ansible inventory generator. |
| [`workstation-capability-reduction.md`](workstation-capability-reduction.md) | Not started — waiting on [`workstation-management.md`](workstation-management.md) | Split the workstation into driving, maintainer, and operator tiers and retire each infrastructure credential from the tiers that no longer need it. |
| [`workstation-management.md`](workstation-management.md) | De-risking | Bring VM 401 under Ansible management: inventory group, role, per-user remote sessions, and a tested account and SSH configuration. |

## By initiative

| Initiative | Track | Phase | Project | Status |
| :--- | :--- | :--- | :--- | :--- |
| `coding-agent-host` | `boundary` | `1-network` | [`coding-agent-network.md`](coding-agent-network.md) | De-risking |
| `coding-agent-host` | `boundary` | `2-host` | [`coding-agent-host.md`](coding-agent-host.md) | Not started — waiting on [`coding-agent-network.md`](coding-agent-network.md) |
| `coding-agent-host` | `boundary` | `3-network-as-code` | [`coding-agent-network-as-code.md`](coding-agent-network-as-code.md) | Not started — waiting on [`tofu-opnsense-day-2.md`](tofu-opnsense-day-2.md), [`coding-agent-network.md`](coding-agent-network.md) |
| `coding-agent-host` | `lifecycle` | — | [`coding-agent-management.md`](coding-agent-management.md) | Not started — waiting on [`tofu-vm-provisioning.md`](tofu-vm-provisioning.md), [`cd-agent.md`](cd-agent.md), [`coding-agent-host.md`](coding-agent-host.md) |
| `coding-agent-host` | `workflow` | `1-access-path` | [`coding-agent-access-path.md`](coding-agent-access-path.md) | Not started — waiting on [`coding-agent-host.md`](coding-agent-host.md), [`workstation-management.md`](workstation-management.md) |
| `coding-agent-host` | `workflow` | `2-molecule-runtime` | [`coding-agent-molecule-runtime.md`](coding-agent-molecule-runtime.md) | Not started — waiting on [`coding-agent-host.md`](coding-agent-host.md) |
| `maintainer-workstation` | `management` | `1-management` | [`workstation-management.md`](workstation-management.md) | De-risking |
| `maintainer-workstation` | `capabilities` | — | [`workstation-capability-reduction.md`](workstation-capability-reduction.md) | Not started — waiting on [`workstation-management.md`](workstation-management.md) |
| `off-site-monitoring` | `monitoring` | `1-on-prem` | [`monitoring-host-isolation.md`](monitoring-host-isolation.md) | Building |
| `off-site-monitoring` | `monitoring` | `2-off-site` | [`off-site-monitoring.md`](off-site-monitoring.md) | De-risking — blocked: no production credential goes to the GCP host until ADR 0047 is approved, and its hardening pass is unscoped |
| `pull-based-cd` | `agent` | — | [`cd-agent.md`](cd-agent.md) | De-risking |
| `pull-based-cd` | `credentials` | — | [`cd-agent-approles.md`](cd-agent-approles.md) | De-risking |
| `pull-based-cd` | `credentials` | — | [`cd-agent-controller-approle-retirement.md`](cd-agent-controller-approle-retirement.md) | Not started — waiting on [`cd-agent.md`](cd-agent.md), [`cd-agent-approles.md`](cd-agent-approles.md) |
| `tofu-vm-provisioning` | `provisioning` | — | [`tofu-vm-provisioning.md`](tofu-vm-provisioning.md) | De-risking |
| `tofu-vm-provisioning` | `migration` | `1-rehearsal` | [`tofu-migration-rehearsal.md`](tofu-migration-rehearsal.md) | Not started — waiting on [`tofu-vm-provisioning.md`](tofu-vm-provisioning.md) |
| `tofu-vm-provisioning` | `migration` | `2-cutover` | [`tofu-migration-cutover.md`](tofu-migration-cutover.md) | Not started — waiting on [`tofu-migration-rehearsal.md`](tofu-migration-rehearsal.md) |
| `tofu-vm-provisioning` | `opnsense` | — | [`tofu-opnsense-day-2.md`](tofu-opnsense-day-2.md) | De-risking — waiting on [`tofu-migration-cutover.md`](tofu-migration-cutover.md) |
