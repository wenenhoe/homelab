---
id: DRAFT-tools-directory-and-secrets-package-split
title: "Split OpenBao/secrets tooling out of cloud_credentials, into its own package"
type: draft-adr
status: decided
---

# Split OpenBao/secrets tooling out of cloud_credentials, into its own package

**Status:** Decided

## Context

`ansible/cloud_credentials/`'s name and stated purpose
(`cloud-credential-creation.md`) is B2/OCI/R2 credential minting — but
`cache.py`, its OpenBao/Vault client, is a different domain entirely
that happens to live there because leaf/rotation credentials are what
it stores. The OpenBao/secrets domain is already scattered further:
`ansible/bootstrap_secrets.py` and `ansible/audit_secrets.py` sit at
`ansible/`'s top level (not in any package), independently duplicating
`cache.py`'s Vault-client logic, and `docker/openbao/watcher/r2_read_watcher.py`
is a third, separate location for the same domain again. This scatter
is what let the identical missing-SSH-timeout bug exist independently
in two files without anyone noticing the duplication
([`0030-openbao-hvac-paramiko-clients.md`](../0030-openbao-hvac-paramiko-clients.md))
— a structural symptom, not just a naming complaint.

`r2_read_watcher.py` is a special case among the three, confirmed by
checking: no Dockerfile anywhere in this repo references it — it's
genuinely hand-installed via `scp` onto `security`'s system Python
(`docs/openbao-r2-read-watcher.md`), never containerized, never part
of the `uv`-managed environment the other three live in. It stays
excluded from actually importing the shared client this split builds,
for the same reason ADR 0030 already gives: sharing code across that
deployment boundary means shipping a whole package alongside a script
whose deployment model deliberately stays a single file. It's grouped
here only as evidence of how scattered this domain already is, not as
a future consumer of `tools/secrets/`.

No `tools/`-shaped root exists in this repo today. Standalone Python
currently lives either inside `ansible/` (as a package or a top-level
script) or under `docker/<app>/` (app-specific, e.g. the watcher).
`pyproject.toml` itself already lives at the repo root, not nested
under `ansible/` — confirmed by checking directly, correcting an
earlier assumption in this draft. Package resolution here is manual
`sys.path`/cwd manipulation throughout (no `[tool.pytest]` config, no
setuptools/package-discovery config, `[tool.uv] package = false`), not
real Python packaging — a `tools/` root works exactly the same way a
new top-level directory under `ansible/` would, and shares the same
root `pyproject.toml` and dependency set trivially. No second
`pyproject.toml`/dependency group is needed.

## Options

### A — Leave the layout as-is

[ADR 0030](../0030-openbao-hvac-paramiko-clients.md)'s hvac/paramiko
work is the only
response. Cheapest, but the domain stays scattered — the next person
adding OpenBao-adjacent tooling has no obvious home, and could
reintroduce a fourth copy of the same client logic.

### B — New root-level `tools/` directory, split by domain

`tools/cloud_credentials/` (B2/OCI/R2 minting, scope unchanged, just
moved) and `tools/secrets/` (the OpenBao/Vault client - `cache.py`'s
generic pieces, `bootstrap_secrets.py`, and the real home for the
shared `hvac`/`paramiko` primitives
[ADR 0030](../0030-openbao-hvac-paramiko-clients.md) left as this
draft's decision to make).
`docker/openbao/watcher/r2_read_watcher.py` stays exactly where it is
and doesn't import from either new location - confirmed no Dockerfile
anywhere references it (never containerized, hand-installed onto
`security`'s system Python instead), so there's no container-build
question to resolve, but its standalone single-file deployment model
is exactly why it doesn't become a `tools/secrets/` consumer either.
`docker/openbao/scripts/`'s shell scripts and
`openbao_backup/snapshot-push.sh.j2` are also candidates for the same
shared client
([`0030-openbao-hvac-paramiko-clients.md`](../0030-openbao-hvac-paramiko-clients.md)).

**Resolved:** the `secrets` Ansible role does not need to import this
package directly. `ansible-collections-audit.md`'s Stage 3 already
plans `community.hashi_vault` (a maintained collection) for that
role's Vault tasks, not a custom import — same principle applied
throughout this repo's tooling: prefer the vendor-maintained module
over a hand-rolled one. Default: `tools/secrets/` is a plain importable
package, no `module_utils`/`library`-shaped packaging needed. Only
revisit that if `community.hashi_vault`'s own spike (already an open
Assumption in the sibling draft) finds it can't reproduce something
this repo specifically needs — e.g. the custom-CA-verify pattern —
in which case Ansible would need to import the shared client directly
after all.

### C — Same split, no new root: `ansible/secrets/` alongside `ansible/cloud_credentials/`

Smaller move, no new top-level directory — but keeps standalone,
non-Ansible Python tooling nested under a directory named for Ansible
specifically, arguably the same kind of naming mismatch this draft
exists to fix (none of this code is a role or a plugin).

## Decision

Leaning **B** — new `tools/` root, split by domain, plain package for
`tools/secrets/` (no Ansible-side packaging complexity, per the
resolution above). Design settled: every Assumption below is resolved
and folded into Context above. Not yet promotable per this repo's own
rule (promotion happens once implemented, not at decide-time) - the
actual move is tracked in
[`tools-secrets-package-split.md`](../../projects/tools-secrets-package-split.md).

## Consequences

Once scoped, the actual move (broken imports, CI paths, systemd units)
is real multi-file mechanical work with regression risk — tracked in
[`tools-secrets-package-split.md`](../../projects/tools-secrets-package-split.md),
separate from this decision of whether/how to do it at all.
