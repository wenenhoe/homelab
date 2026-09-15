---
id: PROJ-tools-secrets-package-split
title: "Split OpenBao/secrets tooling out of cloud_credentials, into tools/"
type: project
status: not-started
summary: "Move ansible/cloud_credentials/ to tools/cloud_credentials/ and extract the scattered OpenBao/Vault client (cache.py, bootstrap_secrets.py, r2_read_watcher.py) into a shared tools/secrets/ package."
---

# Split OpenBao/secrets tooling out of cloud_credentials, into tools/

**Status:** Not started

Moves `ansible/cloud_credentials/` to `tools/cloud_credentials/` and
builds `tools/secrets/` as the real, generically-named home for the
OpenBao/Vault client logic currently duplicated across `cache.py`,
`bootstrap_secrets.py`, and `r2_read_watcher.py` - and already leaked
sideways into `docker/openbao/scripts/bao-*.sh` and
`restore_hosts_scope_from_backup.py`, which import generic
`_security_ssh_target`/`_main_domain`/`read_vault_path` helpers from a
package named for a completely different domain. Design lives in
[`tools-directory-and-secrets-package-split.md`](../decisions/drafts/tools-directory-and-secrets-package-split.md);
this doc tracks build status only. Absorbs what was
`openbao-python-client-hardening.md`'s own Stage 5 (that project has
since closed - its actual hvac/paramiko library decision is
[ADR 0030](../decisions/0030-openbao-hvac-paramiko-clients.md)).

## Stages

| # | Stage | Status |
| :-: | :--- | :--- |
| 1 | Resolve the draft's two remaining Assumptions; promote to a real ADR | Not started |
| 2 | Move `ansible/cloud_credentials/` → `tools/cloud_credentials/` (mechanical) | Not started |
| 3 | Build `tools/secrets/`: extract the generic OpenBao/host-resolution helpers | Not started |
| 4 | Re-point the misplaced-import consumers at `tools/secrets/` | Not started |
| 5 | Re-baseline `cache.py`/`bootstrap_secrets.py`/`r2_read_watcher.py`'s tests | Not started |

## Stage detail

### Stage 1 — Resolve remaining Assumptions

Two unchecked: whether `r2_read_watcher.py` can move out of
`docker/openbao/watcher/` without complicating its container build,
and whether a `tools/` root needs its own `pyproject.toml`/dependency
group. The import-path inventory (the draft's third Assumption) is
already complete - see the draft's Context for the full list, including
the two misplaced-import consumers Stage 4 fixes.

### Stage 3 — Build `tools/secrets/`

Extracts what's genuinely generic out of `cache.py`: `PROJECT_ROOT`,
`_main_domain()`, `_openbao_base_url()`, `_security_ssh_target()`,
`fetch_root_cert_via_ssh()`, `vault_login()`, `vault_read()`,
`vault_write()` - none of this is cloud-credential business, it's
OpenBao/repo-navigation infrastructure that happened to accrete in
`cache.py` because leaf/rotation credentials were its first consumer.
`cache.py`'s own remaining job shrinks to `_vault_path()`'s leaf/
rotation taxonomy and `scoped()`'s session-caching convenience on top
of the generic primitives. `bootstrap_secrets.py` and
`r2_read_watcher.py` become thin callers of the same primitives
instead of independently duplicating them - this is the actual
extraction `openbao-python-client-hardening.md`'s Stage 5 was scoped
to do, now landing in its correct final home instead of a nested
`cloud_credentials/_openbao_client.py` interim location.

### Stage 4 — Re-point misplaced-import consumers

`docker/openbao/scripts/bao-login-from-controller.sh`/
`bao-from-controller.sh`'s `python3 -c "from cloud_credentials.cache
import _security_ssh_target, _main_domain"` and
`restore_hosts_scope_from_backup.py`'s `from cloud_credentials.cache
import PROJECT_ROOT, read_vault_path, write_vault_path` both move to
importing from `tools.secrets` instead - the concrete evidence this
split was needed, not just a naming preference.

## Open items

- Whether `PROJECT_ROOT`'s four independent redefinitions
  (`cache.py`, `bootstrap_secrets.py`, `audit_secrets.py`,
  `restore_all.py`) all centralize on `tools/secrets/`'s copy, or only
  the ones that already import from it for other reasons - not
  decided; a `tools/`-root-level location might fit better than
  `tools/secrets/` specifically, since `restore_all.py`/
  `audit_secrets.py` have nothing to do with secrets. Revisit once
  Stage 2's move settles what else lives at the `tools/` root.
- Whether `docker/openbao/scripts/`'s shell scripts and
  `openbao_backup/snapshot-push.sh.j2` get rewritten in Python against
  `tools/secrets/` directly, dropping their `python3 -c "from ..."`
  one-liner pattern entirely - raised in
  [`openbao-native-cli-not-docker-based-access.md`](../decisions/drafts/openbao-native-cli-not-docker-based-access.md)
  and [`openbao-cli-standardization.md`](openbao-cli-standardization.md),
  not decided here; this project just needs to leave `tools/secrets/`
  in a shape that supports it either way.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes) - run
before deleting this doc once every stage is Done.

- [ ] Every `Done` stage's rationale exists as a real ADR, or plainly
      didn't need one.
- [ ] Every `Done` stage's current behavior is in a topic doc.
- [ ] Every open item is resolved-and-promoted or moved to where it
      belongs next.
- [ ] Every cross-reference into this doc elsewhere in the repo is
      updated or removed.
