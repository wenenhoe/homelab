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
`decision:` isn't gated. `in-progress` and `blocked` are the older
statuses, still valid on projects not yet migrated.

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
- the scope needs to grow.

For the first two, record it (an agent's only permitted ADR edits are in
[`docs/decisions/README.md#assumptions`](../decisions/README.md#assumptions))
and stop; don't improvise around it.

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
| [`doc-workflow-migration.md`](doc-workflow-migration.md) | Building | Move decisions to problem-oriented lineages and projects to the new lifecycle; convert drafts; add agent path-scope enforcement. |
| [`monitoring-host-isolation.md`](monitoring-host-isolation.md) | Building | Bring VM 202 under management and move Beszel/Kuma onto a dedicated on-prem host. |
| [`off-site-monitoring.md`](off-site-monitoring.md) | De-risking — blocked: no production credential goes to the GCP host until ADR 0047 is approved, and its hardening pass is unscoped | Relocate monitoring to a GCP e2-micro so it survives loss of the whole site. |
| [`tofu-vm-provisioning.md`](tofu-vm-provisioning.md) | In progress | OpenTofu-driven Proxmox VM provisioning. |

## By initiative

| Initiative | Track | Phase | Project | Status |
| :--- | :--- | :--- | :--- | :--- |
| `off-site-monitoring` | `off-site` | — | [`off-site-monitoring.md`](off-site-monitoring.md) | De-risking — blocked: no production credential goes to the GCP host until ADR 0047 is approved, and its hardening pass is unscoped |
| `off-site-monitoring` | `on-prem` | — | [`monitoring-host-isolation.md`](monitoring-host-isolation.md) | Building |
| `pull-based-cd` | `agent` | — | [`cd-agent.md`](cd-agent.md) | De-risking |
| `pull-based-cd` | `credentials` | — | [`cd-agent-approles.md`](cd-agent-approles.md) | De-risking |
| `pull-based-cd` | `credentials` | — | [`cd-agent-controller-approle-retirement.md`](cd-agent-controller-approle-retirement.md) | Not started — waiting on [`cd-agent.md`](cd-agent.md), [`cd-agent-approles.md`](cd-agent-approles.md) |
