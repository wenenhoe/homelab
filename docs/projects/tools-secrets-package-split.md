---
id: PROJ-tools-secrets-package-split
title: "Split OpenBao/secrets tooling out of cloud_credentials, into tools/"
type: project
status: in-progress
summary: "Move ansible/cloud_credentials/ to tools/cloud_credentials/ and extract cache.py's generic OpenBao/Vault client pieces (also duplicated in bootstrap_secrets.py) into a shared tools/openbao_client/ package."
---

# Split OpenBao/secrets tooling out of cloud_credentials, into tools/

**Status:** In progress

Moves `ansible/cloud_credentials/` to `tools/cloud_credentials/` and
builds `tools/openbao_client/` as the real, generically-named home for the
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
| 3 | Build `tools/openbao_client/`: extract the generic OpenBao/host-resolution helpers | Done |
| 4 | Re-point the misplaced-import consumers at `tools/openbao_client/` | Done |
| 5 | Dedicated test coverage for `tools/openbao_client/` itself | Done |
| 6 | Split `tools/utils/` out of `tools/openbao_client/` for the non-OpenBao-specific pieces | Done |

## Stage detail

### Stage 1 — Resolve remaining Assumptions

Both resolved by direct inventory, not left as open questions:
`r2_read_watcher.py`'s container-build concern was moot (no Dockerfile
anywhere references it - it's genuinely hand-installed, never
containerized), which also confirmed it should stay independent rather
than import `tools/openbao_client/`, matching ADR 0030's existing reasoning
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

### Stage 3 — Build `tools/openbao_client/`

Done. Extracted what's genuinely generic out of `cache.py`:
`PROJECT_ROOT`, `SECRETS_DIR`, `INVENTORY_PATH`, `read_bootstrap_file()`,
`main_domain()`, `openbao_base_url()`, `security_ssh_target()`,
`fetch_root_cert()`, `vault_login()` (bare - each caller keeps its own
role_id/secret_id file-reading wrapper), `vault_read()`,
`vault_write()` - none of this is cloud-credential business, it's
OpenBao/repo-navigation infrastructure that happened to accrete in
`cache.py` because leaf/rotation credentials were its first consumer.
`cache.py`'s
own remaining job shrinks to `_vault_path()`'s leaf/rotation taxonomy
and `scoped()`'s session-caching convenience on top of the generic
primitives. `bootstrap_secrets.py` became a thin caller of the same
primitives instead of independently duplicating them - this is the
actual extraction `openbao-python-client-hardening.md`'s old Stage 5
was scoped to do, landing in its correct final home instead of a
nested `cloud_credentials/_openbao_client.py` interim location.
`r2_read_watcher.py` keeps its own independent copy (see this project
doc's summary for why) - not a regression, a deliberate exclusion.

Two things found only by actually building and running this, not
assumed going in:

- **Named `tools/openbao_client/`, not `tools/secrets/` as the draft
  originally said.** Confirmed live that `tools/secrets/` would shadow
  Python's own stdlib `secrets` module the moment `tools/` is on
  `sys.path` - `tools/cloud_credentials/verify.py` already does
  `import secrets` for `secrets.token_hex(4)`, which would silently
  break. Caught and fixed before any code was written against the old
  name; the draft was updated in the same patch.
- **`SECRETS_DIR`'s dual-reference testing gotcha.** `from
  openbao_client.client import SECRETS_DIR` in `cache.py`/
  `bootstrap_secrets.py` creates a *separate* name bound to the same
  object at import time - patching `bootstrap_secrets.SECRETS_DIR` in
  a test does nothing to `openbao_client.client`'s own copy, which is
  what `main_domain()`/`read_bootstrap_file()` (defined in that
  module) actually read internally. Every test base class patches
  `openbao_client.client.SECRETS_DIR` at the source now;
  `bootstrap_secrets.py`'s own `SECRETS_DIR` gets patched too, since
  its own code (not just the shared functions it calls) uses that copy
  directly.

`cache.py` still re-exports `PROJECT_ROOT` (`dump_vault_to_file_cache.py`
imports it from there internally, `restore_hosts_scope_from_backup.py`
externally) - deliberately not fixed here, since re-pointing those
imports is Stage 4's job, not a side effect of building the module
they should eventually import from instead.

### Stage 4 — Re-point misplaced-import consumers

Done. `docker/openbao/scripts/bao-login-from-controller.sh`/
`bao-from-controller.sh` now import `security_ssh_target`/`main_domain`
directly (from `utils.repo` as of Stage 6 below; originally
`openbao_client.client`, before that split), and
`restore_hosts_scope_from_backup.py` now imports `PROJECT_ROOT` from
there too - `read_vault_path`/`write_vault_path` stay imported from
`cloud_credentials.cache`, correctly: they're `cache.py`'s own
genuinely cloud-credential-scoped API, calling the shared
`vault_read`/`vault_write` internally, not something misplaced.
`tools/cloud_credentials/dump_vault_to_file_cache.py`'s own
`PROJECT_ROOT` import stays pointed at `cache.py`'s re-export -
internal same-package import, not the cross-package case this stage
targets.

Found by actually running the two shell scripts' Python one-liners,
not assumed: Stage 3 had already silently broken both of them.
`cache.py` stopped defining `_security_ssh_target`/`_main_domain`
entirely once Stage 3 extracted them (as `security_ssh_target`/
`main_domain`, no underscore) - only `PROJECT_ROOT` was re-exported,
so `from cloud_credentials.cache import _security_ssh_target,
_main_domain` started raising `ImportError` the moment Stage 3 landed,
confirmed live before this stage's fix. Anyone who merged Stage 3 on
its own had two broken scripts until this stage closed the gap.

### Stage 6 — Split `tools/utils/` out of `tools/openbao_client/`

Done. Auditing `openbao_client.client`'s actual contents (not
assumed) found most of it was never OpenBao-specific at all - only
`VAULT_KV_MOUNT`, `openbao_base_url()`, `vault_login()`, `vault_read()`,
`vault_write()` genuinely touch OpenBao's API or build its URL.
Everything else - `PROJECT_ROOT`, `SECRETS_DIR`, `INVENTORY_PATH`,
`read_bootstrap_file()`, `main_domain()`, `security_ssh_target()`,
`fetch_root_cert()`, `TIMEOUT_SECONDS` - is generic repo-navigation
and SSH/cert-fetching infrastructure that happened to accrete there
because OpenBao was its first consumer, the same story that motivated
this whole project in the first place. Moved to new
`tools/utils/repo.py`; `openbao_client.client` now imports
`main_domain` from it for `openbao_base_url()`'s own use.

Checked for the same class of naming hazard that renamed
`tools/secrets/` to `tools/openbao_client/` earlier in this project,
before writing any code against the name: no installed dependency
resolves a bare `import utils` today, and none of `ansible-core`/
`docker`/`requests`/`oci`/`b2sdk`/`hvac`/`paramiko` would plausibly
ship one - confirmed live, not assumed.

Every caller re-pointed and re-verified live, not just under mocked
tests: `cache.py`, `bootstrap_secrets.py`,
`restore_hosts_scope_from_backup.py`, and both
`docker/openbao/scripts/bao-*.sh` scripts. Test suites split the same
way the code did - `tools/tests/openbao_client/test_client.py` slimmed
to just the OpenBao-specific functions, new
`tools/tests/utils/test_repo.py` covers the rest, net zero tests lost
or duplicated (61 before the split, 61 after, just regrouped).

## Open items

- `PROJECT_ROOT`'s four independent redefinitions are down to two:
  `cache.py`/`bootstrap_secrets.py` both now import it from
  `tools/utils/repo.py` (Stage 6). Whether `audit_secrets.py`/
  `restore_all.py` also switch to importing it, instead of each
  independently redefining `Path(__file__).resolve().parent.parent`,
  is still open - genuinely tied to
  [`ansible-root-scripts-into-scripts-dir.md`](../decisions/drafts/ansible-root-scripts-into-scripts-dir.md)'s
  own decision, since both files' own `PROJECT_ROOT` line needs its
  parent count bumped either way if that move happens; deciding
  whether to import instead of redefine at the same time avoids
  touching that line twice.
- Whether `bootstrap_secrets.py`/`restore_hosts_scope_from_backup.py`/
  `restore_cloud_credentials_from_backup.py`/`restore_all.py` should
  also physically move to `tools/`, given they now import from it -
  considered and answered no: all four are explicitly gated to the
  `ansible-playbook deploy.yaml` lifecycle (confirmed in each file's
  own docstring; `restore_all.py` shells out to `ansible-playbook`
  directly), which is genuinely `ansible/`'s domain, not generic
  secrets tooling that happens to sit there. Importing from `tools/`
  isn't wrong ownership here - it's the same relationship `cache.py`
  itself has with `openbao_client`. Whether they (plus `audit_secrets.py`)
  should instead move into their own `ansible/scripts/` subdirectory -
  a different question, staying inside `ansible/` either way - is
  [`ansible-root-scripts-into-scripts-dir.md`](../decisions/drafts/ansible-root-scripts-into-scripts-dir.md)'s
  decision, not this project's.

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
