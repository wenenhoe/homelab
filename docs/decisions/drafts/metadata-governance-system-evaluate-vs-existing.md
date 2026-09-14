---
id: DRAFT-metadata-governance-system-evaluate-vs-existing
title: "Metadata-driven doc governance — adopt frontmatter and a narrow NIST subset"
type: draft-adr
status: decided
---

# Metadata-driven doc governance — adopt frontmatter and a narrow NIST subset

**Status:** Decided — see [`doc-governance-metadata.md`](../../projects/doc-governance-metadata.md) for build tracking

## Context

The idea: YAML frontmatter (`id`, `type`, `status`) on
every doc, a generated visibility layer, and a NIST SP 800-53
control-coverage subset — explicitly to demonstrate the ability to
identify and align with NIST for portfolio purposes, not because this
repo has a compliance driver. That framing matters: the goal is a
credible, narrow demonstration, not exhaustive coverage.

Checked directly, not assumed: this repo already has a working,
lightweight version of the core mechanism. `docs/decisions/README.md`
states plainly, *"Promotion to a real ADR happens once the assumptions
are resolved"* — the exact same gate `assumptions_remaining == 0`
would enforce, just currently a human-followed convention (this
session's own drafts use "Claim / Breaks if wrong / Checked by"
bullets as their `assumptions_remaining`, in effect) rather than a
machine-checked field. That mechanism is being kept in prose, not
replaced by a flat array — the "Breaks if wrong"/"Checked by" nuance
doesn't compress into a YAML list without losing information density.

One concrete, already-demonstrated cost worth designing around:
`check-doc-drift.py`'s regex-based checks are already fragile around
Mermaid content — this exact failure mode has already occurred once (a
stray `+` at a line start got misread as a list marker), and the
system's own standing guidance calls out "a Mermaid block right after
a heading can silently break table matching" as a known case. The fix
isn't avoiding Mermaid — `docs/architecture/reverse-proxy-and-dns.md`
already proves it works fine in this repo — it's keeping generated
Mermaid content in its own file, never injected next to anything
regex-parsed.

## Decision

Adopt frontmatter. For the NIST subset: **don't tag it onto individual
docs' frontmatter — write one reference doc instead**, cross-linking to
the ADRs/drafts/projects that already do the thing, without touching
those files themselves.

Two reasons, found in that order while actually trying the per-doc
approach first:

- **No consumer.** A `nist_controls` field with nothing rendering it
  anywhere is inert — the only way to find it is to already know to
  grep frontmatter across four dozen files. That defeats the stated
  goal (demonstrate alignment to a portfolio reader): a reader
  browsing `docs/` would never see it.
- **`docs/README.md`'s own rule**: ADRs are "never edited after
  acceptance (superseded instead)." Adding plain `id`/`type`/`status`
  is defensible as pure structural metadata — it doesn't assert
  anything about the decision itself. Stamping an evaluative NIST
  label onto an already-Accepted ADR is a heavier edit than that: it's
  a claim about the decision's compliance properties, made after the
  fact, by someone other than whoever wrote the ADR. A doc that links
  *to* the ADR instead carries that claim without touching it.

[`docs/nist-800-53-alignment.md`](../../nist-800-53-alignment.md) is
that single doc: a narrow, explicitly-not-compliance narrative — a few
existing practices genuinely resemble a specific 800-53 control, most
don't and aren't forced to, and it says so plainly where a mapping was
evaluated and rejected (see its own notes on `CM-8`).

For visibility: **don't build a new root `INDEX.md`.** Auto-generate
the tables that already exist — `docs/projects/README.md` and
`docs/decisions/drafts/README.md` require a hand-edit every time a
project or draft is added or changes status; that repeated, ongoing
toil is the actual thing worth automating, not a hypothetical one.

Frontmatter schema, kept minimal, `status` scoped per `type`:

```yaml
id: ADR-0027            # or PROJ-<name> / DRAFT-<name>
title: <doc title>
type: adr | draft-adr | project

# type: adr        -> accepted | superseded
# type: draft-adr  -> draft | decided
# type: project    -> not-started | in-progress | done | blocked
status: accepted

superseded_by: ADR-0027   # type: adr, status: superseded only
blocked_reason: <reason>  # type: project, status: blocked only
summary: <one-line>       # type: project only — feeds the generated Covers column
```

No `depends_on` field: a `depends_on` → Mermaid dependency graph was
part of the original plan (Stage 5, optional from the start), but
nothing was ever going to populate it before that stage actually got
built — an unused schema field is the same mistake `nist_controls`
turned out to be above, just caught before it shipped rather than
after. If Stage 5 happens, the field comes back with it.

`status` gained `superseded` during Stage 1 migration: the original
enum had no way to express ADR 0013's actual state
(`Superseded by 0027`) without losing it into prose a generator can't
read. `superseded_by` only appears alongside it — a terminal ADR
state, not a general-purpose cross-doc link.

`status` gained `decided` and `blocked` right after Stage 1, once the
migration's own output made two gaps visible:

- Two drafts' prose already reads "Decided" (this doc included) — a
  draft that's settled but not yet promoted into a numbered ADR. `type:
  draft-adr` already says "unpromoted"; `status: decided` now says
  "and nothing left to resolve" without either field having to imply
  the other. Promotion — moving the file into `decisions/`, assigning
  a number, dropping `Assumptions` — is still the only thing that
  changes a draft's status to `accepted`, and that happens on `type:
  adr`, not on this one.
- `blocked` was never actually a schema gap so much as a generator gap:
  `docs/projects/README.md` and `docs/projects/TEMPLATE.md` already
  document `Blocked: <reason>` as a valid project status line: the
  enum and `blocked_reason` field just catch frontmatter up to
  process that already existed in prose.

`summary` was added during Stage 1, for `type: project` only:
`docs/projects/README.md`'s Covers column carries real per-project
prose that `id`/`title`/`type`/`status` can't derive, and the actual
hand-edit toil this project targets is presence/status churn — not
that description text, which is written once and rarely changes. ADRs
and drafts don't carry it; no generated table currently needs it there.

No `assumptions_remaining` array — the existing prose section stays
authoritative; a generator can count open `Claim` bullets for a
lightweight status indicator without duplicating their content.

## Not yet done

- Whether the dependency graph is worth building at all versus just
  the regenerated tables — the tables solve the demonstrated pain by
  themselves; the graph is a nice-to-have, not confirmed necessary.
