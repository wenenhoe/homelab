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
  label (`super_project:`), not a document; see
  [Super Projects](../project-planning.md#super-projects).
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

The generated [Super Projects](../project-planning.md#super-projects) view reads in build order:
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
| `done` | Everything implemented and merged. | `accepted`, or `approved` while another project still names it |

`check-doc-drift.py` enforces the last column, so a revision that drops
back to `working` stops any project `building` on it. A project without
`decision:` isn't gated. Several projects may name one revision; it stays
`approved` until the last of them closes (see
[When a project finishes](#when-a-project-finishes)).

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

A project's `decision:` is singular and gating — it's the one
`check-doc-drift.py` checks against the Lifecycle table above. A
stage's exit condition can still set a *different* lineage's revision
to `accepted` as a side effect; when it does, add that revision to
`also_implements:` (same format as `decision:`, e.g.
`ADR-0050/0`) and say so in prose where the stage is described —
[`coding-agent-access-path.md`](coding-agent-access-path.md)
(`decision: ADR-0055/0`, `also_implements: [ADR-0050/0]`, whose
Stage 2 sets ADR 0050 to `accepted`) is the existing example.
`also_implements:` doesn't gate anything — `check-doc-drift.py` only
confirms each entry resolves to a real revision — it exists so
[`project-planning.md`'s "Decisions awaiting a project"](../project-planning.md#decisions-awaiting-a-project)
view can tell this ADR is covered without scanning every project's
prose for a mention. Don't confuse this with a project that simply has
no `decision:` yet because nothing is `approved` —
[`cd-agent.md`](cd-agent.md) (ADR 0044, still two competing candidates)
is that separate case: no ADR is being carried out there, one just
isn't chosen yet, and it has neither field set.

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
project docs, the generated decisions index and project-planning view
(a status change regenerates both), and the revision the project's
`decision:` names, so the permitted ADR edits stay possible. A
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

A revision that other projects still name in `decision:` stays
`approved`: this project isn't the last, so it closes without touching
the revision. The last project to name a revision sets it `accepted` in
the PR that deletes its doc, which asserts that the whole Decision is
implemented. If part of it isn't, that PR adds a `not-started` successor
project for the remainder, which also means this one isn't the last.
`also_implements:` doesn't count as naming.
[`check-project-close.py`](../../.github/scripts/check-project-close.py)
fails a PR that deletes a project doc and does neither; see
[`docs/ci.md#project-close-check`](../ci.md#project-close-check), and
[ADR 0037 revision 2](../decisions/0037-decision-and-project-documentation-workflow/revision-002.md)
for the reasoning.

### Closing checklist

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] Every bullet of the linked revision's Decision is implemented, or
      named by a successor project.
- [ ] The linked revision is `accepted` (set in the PR that closes the
      last project naming it), another project still names it, or there
      is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc, not only here.
- [ ] Every open item is resolved and promoted, or moved to the ADR or
      project it belongs to next.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.

## Index

| Project | Status | Covers |
| :--- | :--- | :--- |
| [`agent-full-repo-audit.md`](agent-full-repo-audit.md) | Not started — waiting on [`security-findings-repo.md`](security-findings-repo.md) | A periodic coding-agent audit of the whole repo, ADR-aware, run from homelab-security's CI. |
| [`cd-agent-approles.md`](cd-agent-approles.md) | De-risking | Two CIDR-bound AppRoles for the CD agent (deploy and rotation). |
| [`cd-agent-controller-approle-retirement.md`](cd-agent-controller-approle-retirement.md) | Not started — waiting on [`cd-agent.md`](cd-agent.md), [`cd-agent-approles.md`](cd-agent-approles.md) | Delete controller's Era A AppRole; admin access mints short-lived tokens on demand. |
| [`cd-agent.md`](cd-agent.md) | De-risking | A dedicated, pull-based automation host that runs deploy, maintenance, rotation, and freshness jobs. |
| [`cloud-credentials-hardening.md`](cloud-credentials-hardening.md) | De-risking | Selective official-SDK adoption for tools/cloud_credentials, and verify.py's rclone calls to boto3. |
| [`coderabbit-pr-review-pipeline.md`](coderabbit-pr-review-pipeline.md) | Not started — waiting on [`security-findings-repo.md`](security-findings-repo.md) | homelab-security's CI polls this repo for new PRs, runs CodeRabbit against each diff, and writes findings as files. |
| [`coding-agent-access-path.md`](coding-agent-access-path.md) | Not started — waiting on [`coding-agent-host.md`](coding-agent-host.md), [`workstation-management.md`](workstation-management.md) | Terminal-only access to the coding-agent host and the fetch-review-push workflow, so the host never holds or reaches a push credential. |
| [`coding-agent-host.md`](coding-agent-host.md) | Not started — waiting on [`coding-agent-network.md`](coding-agent-network.md) | The dedicated VM, Ansible role, and inventory group that run Claude Code unprivileged under its built-in sandbox. |
| [`coding-agent-management.md`](coding-agent-management.md) | Not started — waiting on [`tofu-vm-provisioning.md`](tofu-vm-provisioning.md), [`cd-agent.md`](cd-agent.md), [`coding-agent-host.md`](coding-agent-host.md) | Rebuild-first management of the coding-agent host from the Tofu definition, with a dedicated key and a CD-agent job that holds nothing else. |
| [`coding-agent-molecule-runtime.md`](coding-agent-molecule-runtime.md) | Not started — waiting on [`coding-agent-host.md`](coding-agent-host.md) | Choose and adopt a container runtime that runs the repo's privileged, systemd-based Molecule scenarios without host-level root on the coding-agent host. |
| [`coding-agent-network-as-code.md`](coding-agent-network-as-code.md) | Not started — waiting on [`tofu-opnsense-day-2.md`](tofu-opnsense-day-2.md), [`coding-agent-network.md`](coding-agent-network.md) | Move the coding-agent VLAN, firewall rules, and proxy configuration from hand-maintained OPNsense state into Tofu. |
| [`coding-agent-network.md`](coding-agent-network.md) | De-risking | A dedicated VLAN, default-deny firewall policy, filtering egress proxy, and canary probes for the coding-agent host. |
| [`monitoring-host-isolation.md`](monitoring-host-isolation.md) | Building | Bring VM 202 under management and move Beszel/Kuma onto a dedicated on-prem host. |
| [`off-site-monitoring.md`](off-site-monitoring.md) | De-risking — blocked: no production credential goes to the GCP host until ADR 0047 is approved, and its hardening pass is unscoped | Relocate monitoring to a GCP e2-micro so it survives loss of the whole site. |
| [`operator-host.md`](operator-host.md) | De-risking | A headless VM in VLAN 30, reachable only from the maintainer's laptop, that takes over the controller's tooling and credentials. |
| [`security-findings-repo.md`](security-findings-repo.md) | Not started | Create homelab-security, the private repo that tracks code-review findings for this public repo. |
| [`tofu-migration-cutover.md`](tofu-migration-cutover.md) | Not started — waiting on [`tofu-migration-rehearsal.md`](tofu-migration-rehearsal.md) | Rebuild on the real VMID ranges, cut over, and decommission the old VMs. |
| [`tofu-migration-rehearsal.md`](tofu-migration-rehearsal.md) | Not started — waiting on [`tofu-vm-provisioning.md`](tofu-vm-provisioning.md) | Build the isolated 5XX block and run the first restore.yaml against it. |
| [`tofu-opnsense-day-2.md`](tofu-opnsense-day-2.md) | De-risking — waiting on [`tofu-migration-cutover.md`](tofu-migration-cutover.md) | Kea, VLAN, and static DNS configured through OPNsense's API. |
| [`tofu-vm-provisioning.md`](tofu-vm-provisioning.md) | De-risking | Tofu skeleton, Ubuntu and OPNsense modules, and the Tofu-to-Ansible inventory generator. |
| [`workstation-capability-reduction.md`](workstation-capability-reduction.md) | Not started — waiting on [`operator-host.md`](operator-host.md), [`workstation-management.md`](workstation-management.md) | Remove every infrastructure credential and the controller tooling from VM 401 once the operator host runs the controller. |
| [`workstation-management.md`](workstation-management.md) | Not started — waiting on [`operator-host.md`](operator-host.md) | Bring VM 401 under Ansible management from the operator host, with SSH client configuration and a TLS remote desktop. |
