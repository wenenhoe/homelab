---
id: EXP-new-system-planning
title: "What must be settled before a new system is added, and where is it kept?"
type: exploration
status: open
summary: "Which questions about zone, flows, shared services and resources a new system answers before it is built, and whether they belong in the exploration, the service record, the flow list or a capacity table."
topic: documentation-process
related: [ADR-0037, ADR-0094, ADR-0100]
---

# What must be settled before a new system is added, and where is it kept?

A new system arrives through an exploration, a decision, a project and a service
record, and each of those is checked. What nothing asks is where it runs, what
must reach it, which shared services it leans on, and whether the node has room.
Those answers end up scattered across the decisions that needed them, and are
found when two decisions turn out to assume the same shared service. The
question is which of them to ask earlier, and where to write them down.

## What bears on it

- **The record is asked at the end.** The seven sections of
  [ADR 0100](../decisions/0100-recording-how-a-system-is-integrated/revision-001.md)
  are acceptance criteria in the
  [project template](../projects/TEMPLATE.md), and the drift check requires them
  once a catalog app exists. The [exploration template](TEMPLATE.md) asks nothing
  about a system, so the questions first meet the work after its design is chosen.
- **No section asks for the zone.** `Exposure` asks what reaches the system and
  what it reaches, but not which VLAN it is in or which zones must be admitted. The
  [`bind9` record](../topics/records/bind9.md) shows the result: its `Exposure`
  says it is unknown which networks can reach port 53.
- **Choosing a zone has no criteria.** The scheme in
  [`vm-provisioning.md`](../topics/infra/vm-provisioning.md#vmid--vlan--ip-scheme)
  says what each VMID block is for, and that a block holds hosts of one trust level.
  It does not say how a new host picks one, and a new zone costs an edit to the
  gateway's seed because the pinned release cannot assign an interface through its
  API ([ADR 0089](../decisions/0089-how-the-opnsense-gateway-is-configured/revision-000.md)).
- **The flow list covers the zones it declares.** `flows.yaml` states the expected
  flows between the five zones of the gateway's play, and its rules require a flow
  for every ordered pair of declared zones
  ([`network-boundary-checks.md`](../topics/infra/network-boundary-checks.md#what-the-loader-and-rules-enforce)).
  A zone that is not declared there is not checked, so a system placed in one
  produces no failure.
- **Shared services have no list of consumers.** ADR 0053, ADR 0058 and ADR 0114
  each assume the same forward proxy, and none lists who else uses it. The
  records' `Dependencies` section says what needs a catalog app, which does not
  reach a service that is not one: a proxy, a resolver or the gateway's own
  services.
- **Sizing is a literal and a repeated remark.** `cores`, `memory_mb` and `disk_gb`
  are set in `tofu/main.tf` and `tofu/canaries.tf`. The node's size and an early
  accounting of its headroom are in
  [ADR 0035](../decisions/0035-container-orchestration-platform/revision-000.md), and
  projects repeat that the node has limited headroom. Nothing sums the VMs
  against the node. Figures about the lab's own capacity are not a weakness, so
  [`data-classification.md`](../topics/engineering/data-classification.md)
  would place them in the public class; confirm that before writing any.

## Options

- **Put the questions in the exploration template.** An optional section for a
  question that introduces a system: zone and why, flows in and out as
  `flows.yaml` entries, shared services used or provided, resources against the
  node, and exposure. Costs one template section and nothing to maintain. It
  moves the questions earlier and checks nothing, so it works only while it is
  read.
- **Add a `Placement` section to the service record.** The zone, the flows it
  needs and the shared services it uses, between `Dependencies` and `Data`. The
  record is an accepted decision's output, so a new section is a new revision of
  ADR 0100, a change to the drift check and a line in each existing record, or an
  entry on the exemption list. It would have made the `bind9` unknown a failure
  instead of a sentence. A cheaper form widens `Exposure` to name the zone and the
  flows, with the same revision and no new section.
- **Make the flow list part of a project's required checks.** A project that adds a
  zone or a cross-zone flow carries the `flows.yaml` entries in the same change,
  as one line in the project template's acceptance criteria. Costs a line, and
  catches the missing flow at the project, not at the next probe run.
- **A shared-services table.** One topic doc listing each shared service, its home
  zone and its consumers. A hand-kept table drifts, as every count does here
  ([`docs/README.md`](../README.md)); the alternative is to require that a shared
  service's own record list its consumers under `Dependencies`, which adds no doc
  and reaches only what has a record.
- **A capacity table.** A topic doc with the node's resources and each VM's
  sizing, written by hand or generated from the Tofu module calls so it cannot
  drift. A generated one needs a small generator and a ceiling the maintainer sets;
  a hand-written one is the same remark as today in a table. Without a ceiling a
  check has nothing to compare against.

## Leaning

Start with the three that cost a line each: the exploration template's optional
section, the `flows.yaml` line in the project template, and `Exposure` widened to
name the zone and the flows, which is one revision of ADR 0100. Leave the
shared-services table until a second shared service exists to show whether
`Dependencies` is enough. The capacity table is the one most likely to be skipped
and the only answer to the sizing gap, so it deserves its own exploration once
the node's figures are written down.
