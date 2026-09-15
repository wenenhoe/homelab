---
id: PROJ-tools-secrets-package-split
title: "Split OpenBao/secrets tooling out of cloud_credentials, into tools/"
type: project
status: in-progress
summary: "Move ansible/cloud_credentials/ to tools/cloud_credentials/ and extract cache.py's generic OpenBao/Vault client pieces (also duplicated in bootstrap_secrets.py) into a shared tools/secrets/ package."
---

# Split OpenBao/secrets tooling out of cloud_credentials, into tools/

**Status:** In progress

Moves `ansible/cloud_credentials/` to `tools/cloud_credentials/` and
builds `tools/secrets/` as the real, generically-named home for the
OpenBao/Vault client logic currently duplicated across `cache.py` and
`bootstrap_secrets.py` - and already leaked sideways into
`docker/openbao/scripts/bao-*.sh` and
`restore_hosts_scope_from_backup.py`, which import generic
`_security_ssh_target`/`_main_domain`/`read_vault_path` helpers from a
package named for a completely different domain. `r2_read_watcher.py`
shares the same duplicated logic but stays independent - its
hand-installed, single-file deployment model means it can't cleanly
import a shared package the way the other two can. Design lives in
[`tools-directory-and-secrets-package-split.md`](../decisions/drafts/tools-directory-and-secrets-package-split.md);
this doc tracks build status only. Absorbs what was
`openbao-python-client-hardening.md`'s own Stage 5 (that project has
since closed - its actual hvac/paramiko library decision is
[ADR 0030](../decisions/0030-openbao-hvac-paramiko-clients.md)).

## Stages

| # | Stage | Status |
| :-: | :--- | :--- |
| 1 | Resolve the draft's two remaining Assumptions | Done |
| 2 | Move `ansible/cloud_credentials/` → `tools/cloud_credentials/` (mechanical) | Done |
| 3 | Build `tools/secrets/`: extract the generic OpenBao/host-resolution helpers | Not started |
| 4 | Re-point the misplaced-import consumers at `tools/secrets/` | Not started |
| 5 | Re-baseline `cache.py`/`bootstrap_secrets.py`'s tests | Not started |

## Stage detail

### Stage 1 — Resolve remaining Assumptions

Both resolved by direct inventory, not left as open questions:
`r2_read_watcher.py`'s container-build concern was moot (no Dockerfile
anywhere references it - it's genuinely hand-installed, never
containerized), which also confirmed it should stay independent rather
than import `tools/secrets/`, matching ADR 0030's existing reasoning
for why it doesn't share code with the other two. The `pyproject.toml`
question resolved the other way: it already lives at the repo root
(not nested under `ansible/`, correcting the draft's original
premise), and package resolution here is manual `sys.path`/cwd-based
throughout, so a `tools/` root shares it with no changes needed.

### Stage 2 — Move `ansible/cloud_credentials/` → `tools/cloud_credentials/`

Done. The real scope was larger than the pre-move checklist below
estimated, confirmed by actually running the affected scripts, not
just grepping: four files import `cloud_credentials` with no explicit
`sys.path` setup, relying entirely on cwd (`audit_secrets.py`,
`bootstrap_secrets.py`, `restore_cloud_credentials_from_backup.py`,
`restore_hosts_scope_from_backup.py`) - each now has an explicit
`sys.path.insert(..., "tools")` rather than relying on cwd. The two
`docker/openbao/scripts/bao-*.sh` scripts `cd`'d into `ansible/` to
run their `python3 -c "from cloud_credentials.cache import ..."`
one-liner - now `cd`s into `tools/` instead. CI needed its job
structure changed, not just a path-filter glob: the `python-unit-tests`
job's `working-directory: ansible` + `pytest tests/` became
`pytest ansible/tests/ tools/tests/ -v` from the repo root, since
`tools/tests/` is a sibling directory Molecule-style
`working-directory` scoping can't reach. `pyproject.toml`'s
`ansible/tests/**` per-file-ignore needed a `tools/tests/**`
counterpart too - ruff caught this one itself.

Pre-move checklist, confirmed accurate for what it covered:

- `python3 -m cloud_credentials.X` invocation strings needing a
  rename: `docs/cloud-credential-creation.md` (8 occurrences),
  `docs/secrets-rotation.md`, `docs/openbao-reinit-runbook.md`
  (`dump_vault_to_file_cache`, `diff_vault_backups`).
- One systemd unit:
  `tools/cloud_credentials/systemd/check-freshness.service`'s
  `ExecStart=/usr/bin/python3 -m cloud_credentials.check_freshness`.
- The test tree mirrors the package structure
  (`ansible/tests/cloud_credentials/{leaf_keys,rotation_keys}/`) and
  moved with it.
- `PROJECT_ROOT`'s four independent redefinitions (`cache.py`,
  `bootstrap_secrets.py`, `audit_secrets.py`, `restore_all.py`) are a
  smaller instance of the same root cause, worth centralizing in the
  same move rather than a separate effort - see Open items below for
  where it should actually live.

### Stage 3 — Build `tools/secrets/`

Extracts what's genuinely generic out of `cache.py`: `PROJECT_ROOT`,
`_main_domain()`, `_openbao_base_url()`, `_security_ssh_target()`,
`fetch_root_cert_via_ssh()`, `vault_login()`, `vault_read()`,
`vault_write()` - none of this is cloud-credential business, it's
OpenBao/repo-navigation infrastructure that happened to accrete in
`cache.py` because leaf/rotation credentials were its first consumer.
`cache.py`'s own remaining job shrinks to `_vault_path()`'s leaf/
rotation taxonomy and `scoped()`'s session-caching convenience on top
of the generic primitives. `bootstrap_secrets.py` becomes a thin
caller of the same primitives instead of independently duplicating
them - this is the actual extraction `openbao-python-client-hardening.md`'s
Stage 5 was scoped to do, now landing in its correct final home
instead of a nested `cloud_credentials/_openbao_client.py` interim
location. `r2_read_watcher.py` keeps its own independent copy (see
this project doc's summary for why) - not a regression, a deliberate
exclusion.

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
