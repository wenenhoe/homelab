# Agent instructions

Read this before changing any code, config, or doc in this repo. Some
rules live here directly (below); larger or more structural ones are
pointed to instead.

- [`docs/decisions/README.md`](docs/decisions/README.md) — decision
  lineages, the revision states, and exactly what an agent may edit in
  an ADR.
- [`docs/projects/README.md`](docs/projects/README.md) — the project
  lifecycle and the stop conditions.
- [`docs/README.md`](docs/README.md) — where each kind of doc goes, and
  the public-repo rule.
- [`docs/topics/engineering/conventions.md`](docs/topics/engineering/conventions.md)
  — naming and structural rules that span components, including the
  Python unit test conventions (style, fixtures, test doubles,
  assertions). Read it before writing or changing a test.

Before implementing a project, open its `decision:` revision.
`approved` means proceed; anything else means stop and ask.

A change that touches a project doc may only change that project's
`allowed_paths` (plus the project docs, the generated decisions index
and project-planning view, and its own decision revision). Work that needs a file outside them
stops there; see [`docs/projects/README.md#scope`](docs/projects/README.md#scope).

Verify a docs change with `pre-commit run --all-files`; it regenerates
the indexes, lints the markdown, and runs
[`check_doc_drift.py`](tools/doc_scripts/check_doc_drift.py).

## Security and reliability defaults

- **Public exposure.** Every app in `compose_apps` is proxied through
  Caddy with Tinyauth forward-auth and TLS by default;
  [`docs/topics/deploy/adding-an-app.md`](docs/topics/deploy/adding-an-app.md)'s `routes` block only
  accepts `auth: false` as an explicit, per-route opt-out — there's no
  default-open path.
- **Least privilege.** Non-root containers and scoped AppRoles are the
  standing pattern, not a per-component judgment call — see
  [ADR 0004 (Docker API access)](docs/decisions/0004-container-access-to-the-docker-api/revision-000.md),
  [ADR 0020 (Automation identity scope)](docs/decisions/0020-automation-identity-and-access-scope/revision-000.md),
  and [ADR 0043 (Host hardening baseline)](docs/decisions/0043-host-os-hardening-baseline/revision-000.md)
  for where it's reasoned through role by role.
- **Idempotency.** Every Molecule scenario runs a real `idempotence`
  check — converge twice, second run reports no changes — except ones
  documented otherwise (rotation, one-shot jobs, timed renewal; see
  [`docs/topics/engineering/molecule-testing.md`](docs/topics/engineering/molecule-testing.md)). A role that
  can't pass this either earns a documented exception there or isn't
  done.

## Comment discipline

A comment states a fact and why it matters — not a narration of how it
was found, and not a "verify before relying on this" hedge. The
pre-commit config's own comments are the existing model: the
`ansible-lint` override states the upstream `always_run` quirk and that
it was checked "against the actual ansible/ansible-lint manifest, not
assumed"; the locale override states what `ansible-core` requires and
why `C.UTF-8` specifically, not that it might work.

A comment earns its place only if removing it could let a real bug
back in — non-obvious ordering, a tool quirk, a security-relevant
default. Reasoning that doesn't meet that bar goes in a commit message
or a doc instead of padding the code. If the same explanation would
apply in two places, it has one home and the other links to it — the
same rule [`docs/README.md`](docs/README.md) states for docs
cross-referencing each other, applied to code comments pointing at
docs.

A comment, error message, docstring or topic doc describes what the code
does now. It never names a project's stage, phase or track (a label like
"Track A" or "stage 2") or the migration it came from: that vocabulary
belongs to the project doc and is deleted with it, and a leftover reads
as work still pending.

## Verification before writing it down

- Quote a doc's or config's own line when its exact expected format
  matters; don't infer a shape and write it down as if confirmed.
- A test fixture that mirrors production (a DB, a proxy, a storage
  backend) is derived from the actual production config and diffed
  against it, not authored independently from memory.
- A test for a side effect asserts the side effect happened (a
  timestamp changed, a file exists, a KV version incremented) — see
  [`docs/topics/engineering/molecule-testing.md`](docs/topics/engineering/molecule-testing.md)'s
  `rotate_secret` scenario for a real example — not just that a task
  exited zero.
