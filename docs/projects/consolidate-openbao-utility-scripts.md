---
id: PROJ-consolidate-openbao-utility-scripts
title: "Consolidate OpenBao utility scripts into tools/openbao_utils/"
type: project
status: in-progress
summary: "Rename tools/openbao_client/ to tools/openbao_utils/; move and rename bootstrap_secrets.py, audit_secrets.py, the two restore_*_from_backup.py scripts (merged), dump_vault_to_file_cache.py, and diff_vault_backups.py into it; move restore_all.py and molecule-test-all.sh into a new ansible/scripts/."
---

# Consolidate OpenBao utility scripts into tools/openbao_utils/

**Status:** In progress

Renames `tools/openbao_client/` to `tools/openbao_utils/`, moves five
scripts into it (merging two into one, shortening every name now that
the package supplies context), pulls two more out of
`tools/cloud_credentials/` that never belonged there, and gives
`ansible/`'s remaining genuine orchestration scripts a home in a new
`ansible/scripts/`. Design lives in
[`consolidate-openbao-utility-scripts.md`](../decisions/drafts/consolidate-openbao-utility-scripts.md);
this doc tracks build status only. Replaces this project's own earlier
"ansible-root-scripts-into-scripts-dir" project - never started, no
code written against it.

## Stages

| # | Stage | Status |
| :-: | :--- | :--- |
| 1 | Rename `tools/openbao_client/` → `tools/openbao_utils/` | Done |
| 2 | Move + rename `bootstrap_secrets.py` → `openbao_utils/bootstrap.py` | Done |
| 3 | Move + rename `audit_secrets.py` → `openbao_utils/audit.py` | Done |
| 4 | Merge both restore scripts → `openbao_utils/restore.py` | Done |
| 5 | Move + rename `dump_vault_to_file_cache.py`/`diff_vault_backups.py` | Done |
| 6 | Move `restore_all.py`/`molecule-test-all.sh` → `ansible/scripts/` | Not started |
| 7 | Add ADR 0031's pointer note; re-inventory and fix every reference | Not started |

## Stage detail

### Stage 1 — Rename the package

Done. Every importer of `openbao_utils.client` updated:
`tools/cloud_credentials/cache.py`, `ansible/bootstrap_secrets.py`,
`ansible/restore_hosts_scope_from_backup.py`'s stale comment,
`docker/openbao/scripts/bao-login-from-controller.sh`'s stale comment
(`bao-from-controller.sh` had none), and every test file - a single
bulk substitution across all of them, since "openbao_client" never
appears as a substring of anything else in this codebase (confirmed by
grepping before touching anything). Verified live, not just under
mocks: direct `openbao_utils.client` import, the full `cache.scoped()`
chain, `bootstrap_secrets.py`, and `restore_hosts_scope_from_backup.py`
all re-run end to end.

Found and fixed a real, pre-existing gap while touching this file's CI
trigger paths: `tools/openbao_utils/**` (then `openbao_client`) and
`tools/utils/**` were never added as their own
`python_unit_tests` trigger paths since Stages 3/6 created them -
only incidentally covered if a paired test file also changed in the
same PR. Added both, and updated `docs/ci.md`'s description to match.

### Stage 2 — Move + rename `bootstrap_secrets.py`

Done. Moved to `tools/openbao_utils/bootstrap.py`; the `sys.path.insert`
it used to reach `tools/` from `ansible/` is gone entirely, since it's
already inside `tools/` now. Absolute imports confirmed as the right
convention by checking `cloud_credentials`'s own scripts first
(`create_leaf_keys.py` imports `cloud_credentials.leaf_keys.b2` in
full, not relatively, despite being siblings) - `bootstrap.py` does
the same for `openbao_utils.client`.

Two real bugs caught by actually running things, not assumed clean
after a mechanical rename:

- **Its test file's string-based `@patch("bootstrap.X")` calls would
  have silently failed.** `bootstrap` isn't importable as a bare
  top-level name - only as `openbao_utils.bootstrap`, since only
  `tools/` is on `sys.path`. Fixed all of them to
  `@patch("openbao_utils.bootstrap.X")`; confirmed by actually running
  the test file before assuming the mechanical rename was enough.
- **Two `secrets` role molecule scenarios
  (`vault_manual_missing`/`manual_missing`) asserted on the literal
  string `'bootstrap_secrets.py'` inside `ensure_secret.yaml`'s error
  message** - which this stage's own invocation-string update
  (`python3 ansible/bootstrap_secrets.py` → `cd tools && python3 -m
  openbao_utils.bootstrap`) removed entirely from that message. Fixed
  both assertions to check `'openbao_utils.bootstrap'` instead. Found
  by inventorying every reference before touching invocation text, not
  after something broke.

Also confirmed, before touching it: `ansible/playbooks/bootstrap-secrets.yaml`
(hyphen, `.yaml`) is a real, separate Ansible playbook - not this
script, despite the similar name. Left untouched.

Repo-wide inventory (~40 files: CI config, `README.md`, playbooks,
role tasks, `cloud_credentials`'s own scripts, ~10 docs, several
decision docs) fixed file by file, checking each one's actual context
rather than a blind bulk substitution - historical/narrative mentions
in already-accepted ADRs were left alone (same judgment call as
Stage 1's rename), only genuine present-tense staleness fixed. Four
lines exceeded the 160-char lint limit once the longer name pushed
them over; shortened rather than wrapped, since they're short
user-facing hints, not documentation.

### Stage 3 — Move + rename `audit_secrets.py`

Done. Moved to `tools/openbao_utils/audit.py`. Went further than a
pure rename: `audit_secrets.py` was one of the two files (with
`restore_all.py`) still independently redefining
`PROJECT_ROOT = Path(__file__).resolve().parent.parent` rather than
importing it - since it was moving into `tools/openbao_utils/` anyway
(same package `client.py` and, now, `bootstrap.py` already live in),
switched it to `from utils.repo import PROJECT_ROOT, SECRETS_DIR`
instead of perpetuating a third local copy. Resolves half of ADR
0031's still-open "`PROJECT_ROOT`'s four independent redefinitions"
item down to one (`restore_all.py`, which stays in `ansible/scripts/`
per this project's own Decision) - updated that ADR's Consequences
directly, matching the "update stale status language in the same
patch that resolves it" rule rather than leaving it to drift.

Same string-based `@patch("audit_secrets.X")` bug as Stage 2's
`bootstrap.py`, caught the same way (by actually running the tests,
not assuming a mechanical rename was sufficient): fixed to
`@patch("openbao_utils.audit.X")`. `SECRETS_DIR` only needed patching
on the `audit` module itself, not also on `utils.repo` - unlike
`bootstrap.py`, `audit.py` never calls into a `utils.repo` function
that reads `SECRETS_DIR` internally, it only uses the constant
directly in its own code.

Repo-wide inventory much smaller this time (~16 files vs.
`bootstrap.py`'s ~40) - `audit_secrets.py` is an ops tool, not part of
the main deploy flow most docs walk through. Same file-by-file
judgment call as Stage 2: fixed ADR 0030's mentions for consistency
with how its `bootstrap_secrets.py` mentions were already handled
(same document, same non-historical framing throughout), left ADR
0016's/0029's genuinely historical mentions alone.

### Stage 4 — Merge the restore scripts

Done. Two phases in one script: registry-scoped restore (via
`cloud_credentials.cache`'s `read_vault_path`/`write_vault_path`,
formerly `restore_hosts_scope_from_backup.py`) then `LEGACY_CACHE_KEYS`
restore (via each key's own module, formerly
`restore_cloud_credentials_from_backup.py`), one combined summary
covering both - shared accumulator lists across both `for` loops, not
two separate summaries. `openbao-reinit-runbook.md`'s steps 5 and 6
collapsed into one, and every downstream step renumbered (7→6, 8→7,
9→8) - including two internal cross-references within that same file
and one each in `openbao-r2-read-watcher.md` and
`diff_vault_backups.py`'s own docstring, found by grepping for step
numbers before assuming the renumbering was done.

Found a real behavioral bug on merge, not assumed: the two original
scripts disagreed on whether to `.strip()` backup file content before
writing it back to Vault - `restore_hosts_scope_from_backup.py` didn't,
`restore_cloud_credentials_from_backup.py` did. Checked
`dump_vault_to_file_cache.py`'s own write side
(`path.write_text(value)`, no added whitespace) to determine which was
actually correct: the non-stripping behavior, since stripping on
restore would silently corrupt any value with meaningful
leading/trailing whitespace that genuinely existed in Vault. Fixed in
the merge; added a regression test for it in both phases.

Test files merged the same way as their sources, each phase's tests
neutralizing the *other* phase (an empty `LEGACY_CACHE_KEYS` list, or
an empty registry) rather than mocking it away, since `main()` runs
both phases unconditionally and an unmocked real Vault session is the
alternative.

Checked ADR 0025's own "not worth merging into one" Consequences
bullet before merging, since it sounded like it might rule this out -
turned out to be comparing against a different, since-retired tool
(`migrate_legacy_cache_to_vault.py`), reasoning about a *mechanism*
distinction (two source-of-truth conventions) this merge doesn't
actually collapse - both phases stay fully separate internally, only
the file they live in changed. Added a note to that ADR distinguishing
the two, rather than silently doing something that reads as
contradicting it.

### Stage 5 — Move + rename `dump_vault_to_file_cache.py`/`diff_vault_backups.py`

Done. Moved to `tools/openbao_utils/{dump,diff}.py`. `dump.py`
switched its `PROJECT_ROOT` import from `cloud_credentials.cache`'s
re-export to `utils.repo` directly, same reasoning as `audit.py` in
Stage 3 - it was moving into the same package `client.py` lives in
anyway. That switch made `cache.py`'s own `PROJECT_ROOT` re-export
genuinely dead: confirmed by grepping for every remaining importer
before removing it - nothing outside `cache.py`'s own test files
touches it anymore, so the re-export (and its explanatory `# noqa`
comment) came out entirely rather than left as unused code. `diff.py`
needed no import changes at all - confirmed (again) it has zero
`cloud_credentials`/Vault-touching code, pure file comparison.

Found a genuinely broken link while inventorying references, not
assumed fixed by the move alone: ADR 0025 linked directly to
`dump_vault_to_file_cache.py`'s old path
(`../../tools/cloud_credentials/dump_vault_to_file_cache.py`) - fixed
to point at the new location, keeping the old name in the link text
with a "since renamed" note rather than silently swapping it, since
the ADR's own prose is describing a specific historical event (a live
audit run at decision time) using the tool's name as it was then.

Neither test file needed a `sys.path` depth change - both moved from
`tools/tests/cloud_credentials/` to `tools/tests/openbao_utils/`,
the same nesting depth under `tools/`, confirmed before assuming so.

### Stage 7 — References and the ADR pointer

The real work. Every doc/config reference to any of these scripts by
their *old* name needs finding fresh - the predecessor project's
16-file inventory doesn't carry over cleanly, since renames (not just
moves) widen what "references this script" means. Add a short pointer
note to [ADR 0031](../decisions/0031-tools-secrets-package-split.md)
noting this project revises its specific call on where these scripts
land, without editing 0031's own Decision text.

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
