# Agent instructions

Read these before changing anything under `docs/` or implementing a
project. They hold the rules; this file only says where.

- [`docs/decisions/README.md`](docs/decisions/README.md) — decision
  lineages, the revision states, and exactly what an agent may edit in
  an ADR.
- [`docs/projects/README.md`](docs/projects/README.md) — the project
  lifecycle and the stop conditions.
- [`docs/README.md`](docs/README.md) — where each kind of doc goes, and
  the public-repo rule.

Before implementing a project, open its `decision:` revision.
`approved` means proceed; anything else means stop and ask.

A change that touches a project doc may only change that project's
`allowed_paths` (plus the project docs, the generated decisions index,
and its own decision revision). Work that needs a file outside them
stops there; see [`docs/projects/README.md#scope`](docs/projects/README.md#scope).

Verify a docs change with `pre-commit run --all-files`; it regenerates
the indexes, lints the markdown, and runs
[`check-doc-drift.py`](.github/scripts/check-doc-drift.py).
