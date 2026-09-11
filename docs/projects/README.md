# Projects

Status and build sequencing for multi-stage initiatives — not a topic
doc (how something works today) and not an ADR (why a design was
chosen). A project doc owns *where the build stands*, and links out to
the ADRs/drafts and topic docs that carry the rest.

## When this is the right artifact

A project doc is for a genuinely multi-stage, multi-PR initiative with
a real stage table — more than one row that isn't just "done in this
PR." A single-PR feature, however substantial, doesn't qualify: it gets
a topic doc once built, or an ADR if it involved a real contested
choice. If you can't fill in a second stage-table row that represents
actual future work, this isn't a project.

## What goes in one

Same shape as [`TEMPLATE.md`](TEMPLATE.md): a status line, a stage
table (`Not started` / `In progress` / `Done` / `Blocked: <reason>`,
updated at the start and end of each PR that works a stage), and links
from each stage to whatever backs it — an [ADR](../decisions/README.md)
or [draft](../decisions/drafts/) for a decision that stage depended on,
a topic doc once that stage's component is built and stable. An "open
items" section holds things carried into later stages — not resolved
questions dressed up as done.

A project doc never carries rationale or current-behavior detail
itself — those get written once, in an ADR or a topic doc, and the
project doc links to them. If you're about to explain a decision's
trade-offs in a stage's own prose instead of drafting or writing an
ADR, that's the signal to stop and write the ADR instead.

## Stage, Track, Phase — scoped per doc

- **Stage** — a sequential build step within one project. Numbering is
  local to that project doc; it doesn't continue across projects and
  doesn't need to.
- **Track** — an independent, separately-sequenceable workstream within
  one project (used when two pieces of work genuinely don't depend on
  each other until some later joining point). Most projects only need
  one implicit track and can skip the word entirely.
- **Phase** — a capability-maturity split *within* one component (e.g.
  "manual today, API-automated later" for one piece of infrastructure),
  not a top-level sequencing axis. Don't conflate this with Stage.

## Drafts stay drafts

A decision a project's stage depends on that isn't yet verified or
built starts in [`decisions/drafts/`](../decisions/README.md#drafts),
linked from the relevant stage row — unchanged from how decisions
already work outside of projects. Promotion to a numbered ADR happens
the same way it always does: once the assumptions are resolved and the
thing is actually built, not at decide-time.

## When a project finishes

Once every stage is Done and everything durable has a home — an ADR
for each real decision, a topic doc for each built component — the
project doc has nothing left to say that isn't already said better
elsewhere. Delete it rather than trimming it to a pointer or archiving
it as a historical record: a finished project doc's remaining content
is either current-state fact (which belongs in the topic doc it
describes) or build narrative (which this repo's own comment/doc
discipline already treats as not belonging in committed docs once
resolved). Before deleting, run the checklist below — skipping it is
how a real fact quietly gets lost instead of promoted.

### Closing checklist

- [ ] Every `Done` stage's rationale exists as a real ADR (not a
      draft) or is plainly not decision-shaped enough to need one.
- [ ] Every `Done` stage's current behavior is described in a topic
      doc, not only in this project doc.
- [ ] Every "open item" is either resolved and promoted, or explicitly
      still open and moved into whichever topic doc or ADR it belongs
      to next.
- [ ] Every cross-reference into this project doc from elsewhere in
      the repo (README, other docs) is updated or removed.

## Index

| Project | Status | Covers |
| :--- | :--- | :--- |
| [`tofu-vm-provisioning.md`](tofu-vm-provisioning.md) | In progress | OpenTofu-driven Proxmox VM provisioning. |
| [`cd-agent.md`](cd-agent.md) | Not started | Pull-based CD agent, replacing manual deploys and `controller`'s standing AppRole. |
| [`cloud-credentials-hardening.md`](cloud-credentials-hardening.md) | Not started | Selective official-SDK adoption (OCI's `identity_domains` client, `b2sdk`) plus error-handling hardening for `ansible/cloud_credentials`. |
| [`openbao-python-client-hardening.md`](openbao-python-client-hardening.md) | Not started | `hvac` + `paramiko` adoption across every internal OpenBao/SSH client (`cache.py`, `bootstrap_secrets.py`, `audit_secrets.py`, `r2_read_watcher.py`), replacing duplicated hand-rolled clients. |
