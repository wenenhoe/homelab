---
id: ADR-0031
title: "Split OpenBao/secrets tooling out of cloud_credentials, into tools/"
type: adr
status: accepted
---

# 0031. Split OpenBao/secrets tooling out of cloud_credentials, into tools/

**Status:** Accepted

## Context

`ansible/cloud_credentials/`'s name and stated purpose
(`cloud-credential-creation.md`) is B2/OCI/R2 credential minting — but
`cache.py`, its OpenBao/Vault client, was a different domain entirely
that happened to live there because leaf/rotation credentials were
what it stored. The OpenBao/secrets domain was already scattered
further: `ansible/bootstrap_secrets.py` and `ansible/audit_secrets.py`
sat at `ansible/`'s top level (not in any package), independently
duplicating `cache.py`'s Vault-client logic, and
`docker/openbao/watcher/r2_read_watcher.py` was a third, separate
location for the same domain again. This scatter is what let the
identical missing-SSH-timeout bug exist independently in two files
without anyone noticing the duplication
([0030](0030-openbao-hvac-paramiko-clients.md)) — a structural
symptom, not just a naming complaint. Concrete evidence beyond that:
`docker/openbao/scripts/bao-*.sh` and
`restore_hosts_scope_from_backup.py` were already reaching sideways
into `cloud_credentials.cache` for generic `_security_ssh_target`/
`_main_domain`/`read_vault_path` helpers that had nothing to do with
cloud credentials at all.

Two things confirmed live, not assumed, before committing to a
design: a `tools/secrets/` package (the original name) would have
shadowed Python's own stdlib `secrets` module the moment `tools/`
hit `sys.path` — `verify.py` already does `import secrets` for
`secrets.token_hex(4)`, which would have silently broken. And
`pyproject.toml` already lives at the repo root, not nested under
`ansible/` as originally assumed — package resolution here is manual
`sys.path`/cwd manipulation throughout (`[tool.uv] package = false`,
no real Python packaging), so a `tools/` root shares it with no
changes needed.

`r2_read_watcher.py` stays excluded from the shared client entirely:
confirmed no Dockerfile anywhere references it — it's genuinely
hand-installed via `scp` as a single file onto `security`'s system
Python, never part of this `uv`-managed tree. Sharing code across
that deployment boundary would mean shipping a second file alongside
a script whose whole point is staying one file.

Alternatives considered: leaving the layout as-is (cheapest, but the
domain stays scattered and the next OpenBao-adjacent script has no
obvious home); and `ansible/secrets/` alongside
`ansible/cloud_credentials/` (smaller move, but keeps non-Ansible
standalone tooling nested under a directory named for Ansible
specifically — the same kind of naming mismatch this fixes).

## Decision

New root-level `tools/` directory, split by actual domain:
`tools/cloud_credentials/` (B2/OCI/R2 minting, scope unchanged, just
moved) and, initially, `tools/openbao_client/` for the shared
OpenBao/Vault client. Building it surfaced a second, smaller instance
of the exact same problem: most of what had accreted in
`cache.py`/`openbao_client.client` was never OpenBao-specific either
— `PROJECT_ROOT`, `SECRETS_DIR`, `INVENTORY_PATH`,
`read_bootstrap_file()`, `main_domain()`, `security_ssh_target()`,
`fetch_root_cert()` are generic repo-navigation and SSH/cert-fetching
infrastructure, not Vault API calls. Split again, into
`tools/utils/repo.py`, leaving `tools/openbao_client/client.py` with
only what's genuinely OpenBao-specific: `VAULT_KV_MOUNT`,
`openbao_base_url()`, `vault_login()`, `vault_read()`, `vault_write()`.

`ansible/bootstrap_secrets.py`, `restore_hosts_scope_from_backup.py`,
`restore_cloud_credentials_from_backup.py`, and `restore_all.py` stay
in `ansible/` despite importing from `tools/` — considered and
rejected moving them too, since all four are explicitly gated to the
`ansible-playbook deploy.yaml` lifecycle (`restore_all.py` shells out
to `ansible-playbook` directly), which is genuinely `ansible/`'s
domain. Importing from `tools/` isn't wrong ownership here; it's the
same relationship `cache.py` itself has with `openbao_client`/`utils`.
Whether these five scripts (loose at `ansible/`'s own root) should
instead move into `ansible/scripts/` is a separate, later decision,
not reopened here.

> **Revised by**
> [`consolidate-openbao-utility-scripts.md`](drafts/consolidate-openbao-utility-scripts.md):
> the lifecycle-gating test above turned out too coarse
> (`cloud_credentials` scripts are also lifecycle-sequenced and
> correctly live in `tools/` anyway) - that draft moves three of these
> four scripts into `tools/openbao_utils/` after all, on a different
> test (does it drive a playbook, not just run near one). This
> paragraph is left as written for the historical record; it's no
> longer this repo's current design.

`docker/openbao/scripts/bao-login-from-controller.sh`/
`bao-from-controller.sh` and `restore_hosts_scope_from_backup.py` -
the concrete evidence this split was needed - now import
`security_ssh_target`/`main_domain`/`PROJECT_ROOT` from `tools/utils/repo.py`
directly. `read_vault_path`/`write_vault_path` stay `cache.py`'s own
API, correctly: they're genuinely cloud-credential-scoped, calling
the shared `vault_read`/`vault_write` internally rather than
misplaced generic code.

## Consequences

- The identical-bug-in-two-places failure mode this project exists
  to prevent (confirmed real: the missing-SSH-timeout bug already hit
  twice independently) can't recur the same way - one shared
  implementation, not four.
- Found by actually running the affected scripts, not assumed:
  building `tools/openbao_client/` initially broke
  `docker/openbao/scripts/bao-*.sh` (they referenced private names
  `cache.py` no longer defined) until the re-pointing stage caught
  and fixed it. A reminder that "shared module built" and "every
  caller re-pointed" are separate, both-required steps, not one.
- `PROJECT_ROOT`'s four independent redefinitions are down to one:
  `consolidate-openbao-utility-scripts.md`'s own Stage 3 resolved
  `audit.py`'s copy by importing from `tools/utils/repo.py` instead of
  redefining it, while moving the file into `tools/openbao_utils/`.
  Only `restore_all.py` still redefines it locally - whether it
  imports from `tools/utils/repo.py` too stays open, tied to the
  `ansible/scripts/` decision above.
- Every stage's build status lived in `tools-secrets-package-split.md`
  while in progress; that project has now closed per its own closing
  checklist, this ADR is the permanent record.
