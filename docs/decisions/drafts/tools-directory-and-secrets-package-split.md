---
id: DRAFT-tools-directory-and-secrets-package-split
title: "Split OpenBao/secrets tooling out of cloud_credentials, into its own package"
type: draft-adr
status: draft
---

# Split OpenBao/secrets tooling out of cloud_credentials, into its own package

**Status:** Draft

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

No `tools/`-shaped root exists in this repo today. Standalone Python
currently lives either inside `ansible/` (as a package or a top-level
script) or under `docker/<app>/` (app-specific, e.g. the watcher).

## Options

### A — Leave the layout as-is

[ADR 0030](../0030-openbao-hvac-paramiko-clients.md)'s hvac/paramiko
work is the only
response. Cheapest, but the domain stays scattered — the next person
adding OpenBao-adjacent tooling has no obvious home, and could
reintroduce a fourth copy of the same client logic.

### B — New root-level `tools/` directory, split by domain

`tools/cloud_credentials/` (B2/OCI/R2 minting, scope unchanged, just
moved) and `tools/secrets/` (the OpenBao/Vault client,
`bootstrap_secrets.py`/`audit_secrets.py`, and a real home for a shared
hvac/paramiko helper if the sibling draft's Option B wins).
`docker/openbao/watcher/r2_read_watcher.py`'s move is a separate
question — its container build context may need it to stay where it is
or import from the new location; unchecked either way. `docker/openbao/scripts/`'s
shell scripts and `openbao_backup/snapshot-push.sh.j2` are also
candidates for the same shared client
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
resolution above). Not yet promotable — two Assumptions below (the
container-build and `pyproject.toml` questions) are still unchecked;
the import-path inventory is now complete and doesn't block Option B.

## Assumptions

- **Import-path inventory — confirmed complete:**
  - **Genuinely on-topic** (leaf/rotation cloud-credential business,
    unaffected by which domain owns the *client* underneath): every
    import under `cloud_credentials.leaf_keys.*`/`.rotation_keys.*`,
    `create_leaf_keys.py`/`create_rotation_keys.py`/
    `create_snapshot_{readonly,write}_keys.py`/`check_freshness.py`/
    `_legacy_cache_keys.py`, and their own test tree
    (`ansible/tests/cloud_credentials/{leaf_keys,rotation_keys}/`).
  - **Two consumers already reaching outside their own domain into
    `cloud_credentials.cache` for generic infrastructure that isn't
    cloud-credential business at all** - concrete evidence this split
    is needed, not just a naming preference:
    - `docker/openbao/scripts/bao-login-from-controller.sh` and
      `bao-from-controller.sh`: `from cloud_credentials.cache import
      _security_ssh_target, _main_domain`.
    - `ansible/restore_hosts_scope_from_backup.py`: `from
      cloud_credentials.cache import PROJECT_ROOT, read_vault_path,
      write_vault_path` - restoring **host** secrets, not cloud
      credentials, yet borrowing the generic Vault escape hatch from a
      package named for a different domain.
  - **`python3 -m cloud_credentials.X` invocation strings**, all
    genuinely on-topic (leaf/rotation commands), needing a mechanical
    rename if the package moves: `docs/cloud-credential-creation.md`
    (8 occurrences), `docs/secrets-rotation.md`,
    `docs/openbao-reinit-runbook.md` (`dump_vault_to_file_cache`,
    `diff_vault_backups`).
  - **One systemd unit**:
    `ansible/cloud_credentials/systemd/check-freshness.service`'s
    `ExecStart=/usr/bin/python3 -m cloud_credentials.check_freshness`.
  - **CI**: `.github/workflows/pr-checks.yml` path-filters on
    `ansible/cloud_credentials/**` - a one-line glob update on a move.
  - Net effect: the inventory itself doesn't block Option B - every
    reference is either staying together (leaf/rotation business,
    moves as one unit) or is exactly the kind of misplaced-generic-
    infrastructure import this split exists to fix.
  - Related, smaller instance of the same root cause, worth folding
    into the same move rather than a separate effort: `PROJECT_ROOT =
    Path(__file__).resolve().parent.parent[.parent]` is independently
    redefined in four places (`cache.py`, `bootstrap_secrets.py`,
    `audit_secrets.py`, `restore_all.py`) rather than shared - no
    wrong owner, just no shared home to import it from.
- Whether `r2_read_watcher.py` can move out of `docker/openbao/watcher/`
  without complicating its container build (Dockerfile `COPY` paths,
  etc.) — unchecked.
- Whether a `tools/` root needs its own `pyproject.toml`/dependency
  group separate from `ansible/`'s existing one, or can share it — this
  repo's current single-`pyproject.toml`-under-`ansible/` shape isn't
  yet confirmed compatible with a sibling `tools/` root.

## Consequences

Once scoped, the actual move (broken imports, CI paths, systemd units)
is real multi-file mechanical work with regression risk — tracked in
[`tools-secrets-package-split.md`](../../projects/tools-secrets-package-split.md),
separate from this decision of whether/how to do it at all.
