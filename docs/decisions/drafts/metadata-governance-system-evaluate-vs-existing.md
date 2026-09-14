---
id: DRAFT-metadata-governance-system-evaluate-vs-existing
title: "Metadata-driven doc governance — adopt frontmatter and a narrow NIST subset"
type: draft-adr
status: decided
---

# Metadata-driven doc governance — adopt frontmatter and a narrow NIST subset

**Status:** Decided — see [`doc-governance-metadata.md`](../../projects/doc-governance-metadata.md) for build tracking

## Context

The idea: YAML frontmatter (`id`, `type`, `status`, `nist_controls`,
`depends_on`) on every doc, a generated visibility layer, and a NIST
SP 800-53 control-coverage subset — explicitly to demonstrate the
ability to identify and align with NIST for portfolio purposes, not
because this repo has a compliance driver. That framing matters: the
goal is a credible, narrow demonstration, not exhaustive coverage.

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

Adopt frontmatter. Adopt a narrow NIST subset, mapped onto practices
that already exist rather than inventing new process to satisfy a
control:

| Control | Where it already lives |
| :--- | :--- |
| RA-3 (Risk Assessment) | Every draft's `Assumptions` section |
| CM-8 (Component Inventory) | `app_registry`/`host_vars` |
| CM-2 (Baseline Configuration) | The Ansible roles themselves |
| CA-7 (Continuous Monitoring) | Beszel/Kuma/`check_freshness`/push monitors |
| CP-9 (System Backup) | `cloud_sync`/`openbao_backup` |
| AC-2/IA-2 (Account Mgmt/Auth) | The OpenBao AppRole/`hvac` work |

Tag `nist_controls` only where a mapping is genuinely true — most docs
will have none, and that's correct, not incomplete.

For visibility: **don't build a new root `INDEX.md`.** Auto-generate
the tables that already exist — `docs/projects/README.md` and
`docs/decisions/drafts/README.md` require a hand-edit every time a
project or draft is added or changes status; that repeated, ongoing
toil is the actual thing worth automating, not a hypothetical one. A
dependency graph (`depends_on` → Mermaid), if
built, goes in its own file, isolated from anything `check-doc-drift.py`
parses — not injected into the same files as the regenerated tables.

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
nist_controls: []         # omit entirely if none apply
depends_on: []            # doc IDs, only when a real dependency exists
```

`status` gained `superseded` during Stage 1 migration: the original
enum had no way to express ADR 0013's actual state
(`Superseded by 0027`) without losing it into prose a generator can't
read. `superseded_by` only appears alongside it — a terminal ADR
state, not a general-purpose link, so it's kept separate from
`depends_on`.

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

- Wiring the generator into the existing pre-commit hook alongside
  `check-doc-drift.py`/markdownlint — tracked as build work in the
  project doc, not decided here.
- Whether the dependency graph is worth building at all versus just
  the regenerated tables — the tables solve the demonstrated pain by
  themselves; the graph is a nice-to-have, not confirmed necessary.
- Tagging the confirmed NIST subset onto the docs where it's genuinely
  true — separate pass from frontmatter migration itself.
