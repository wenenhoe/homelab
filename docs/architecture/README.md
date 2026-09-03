# Architecture & System Design

Pictures of what the system looks like right now: components, how they
talk to each other, and how data moves through it. This directory holds
only the views that don't have one natural home in a single topic doc —
if a diagram would just illustrate one existing page, it lives embedded
in that page instead (e.g. [`deployment-flow.md`](../deployment-flow.md)
has its own play-order diagram).

Split into one high-level diagram (`system-overview.md` — the whole
fleet, at a glance) and several low-level ones (one concern each: DNS
routing, auth, backup/restore). A single diagram trying to show every
cross-host concern at once stops being something you can read at a
glance — that's a sign to split by concern, not to add more subgraphs
to the one diagram.

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

## Index

| Doc | Covers |
| :--- | :--- |
| [`system-overview.md`](system-overview.md) | High-level: the four hosts, controller, and cloud targets, at a glance. Links out to the low-level diagrams below. |
| [`reverse-proxy-and-dns.md`](reverse-proxy-and-dns.md) | Low-level: how a hostname resolves and reaches the right host's Caddy, wildcard TLS via DNS-01. |
| [`auth-flow.md`](auth-flow.md) | Low-level: Tinyauth forward-auth + LLDAP, and the one host that skips it. |
| [`backup-and-restore-data-flow.md`](backup-and-restore-data-flow.md) | Low-level: how a backup moves from an app host to SeaweedFS to the cloud targets, and how a restore reverses that path — spans `disaster-recovery.md`, `cloud-sync.md`, and `restore.md`, none of which has this end-to-end view on its own. |

## Keeping these current

Update the relevant diagram in the same PR that changes the topology it
shows (a new host, a new cross-host data path, a changed backup
destination) — not as a follow-up cleanup pass. If a diagram and its
linked doc ever disagree, the prose doc is the source of truth; open an
issue against the diagram rather than trusting it over the doc it's
illustrating.
