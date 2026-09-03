# Architecture & System Design

Pictures of what the system looks like right now: components, how they
talk to each other, and how data moves through it. This directory holds
only the views that don't have one natural home in a single topic doc —
if a diagram would just illustrate one existing page, it lives embedded
in that page instead (e.g. [`deployment-flow.md`](../deployment-flow.md)
has its own play-order diagram).

This is a different kind of artifact from [`docs/decisions/`](../decisions/README.md):
a diagram says **what exists**; a decision record says **why**. Keep
them separate rather than folding rationale into a diagram's labels —
a diagram that tries to also explain itself stops being something you
can glance at.

Diagrams here are plain [Mermaid](https://mermaid.js.org/) in fenced
code blocks — no separate modeling tool or generated build step. That's
a deliberate ceiling: this is a single-operator repo with a small,
slow-changing set of hosts, so a diagram a person updates by hand in the
same PR as the change it reflects is more trustworthy here than one a
separate tool infers after the fact. Revisit that choice if this ever
grows past a few hosts or gains more than one active contributor.

## Keeping these current

Update the relevant diagram in the same PR that changes the topology it
shows (a new host, a new cross-host data path, a changed backup
destination) — not as a follow-up cleanup pass. If a diagram and its
linked doc ever disagree, the prose doc is the source of truth; open an
issue against the diagram rather than trusting it over the doc it's
illustrating.
