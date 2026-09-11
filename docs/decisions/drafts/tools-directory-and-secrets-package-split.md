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
([`openbao-client-hvac-paramiko-adoption.md`](openbao-client-hvac-paramiko-adoption.md))
— a structural symptom, not just a naming complaint.

No `tools/`-shaped root exists in this repo today. Standalone Python
currently lives either inside `ansible/` (as a package or a top-level
script) or under `docker/<app>/` (app-specific, e.g. the watcher).

## Options

### A — Leave the layout as-is

`openbao-python-client-hardening.md`'s hvac/paramiko work is the only
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
or import from the new location; unchecked either way. A further
wrinkle since this draft was first written: `docker/openbao/scripts/`'s
shell scripts and `openbao_backup/snapshot-push.sh.j2` are also
candidates for the same shared client
([`openbao-client-hvac-paramiko-adoption.md`](openbao-client-hvac-paramiko-adoption.md)),
and the `secrets` Ansible role's Vault tasks might go through
`community.hashi_vault` instead of importing this package directly —
which changes what "who consumes it" even means. If any Ansible task
needs to import the shared client directly rather than through a
collection module, that's an `ansible/roles/*/library/`- or
`module_utils`-shaped need, a different packaging mechanism than a
plain `tools/` package standalone scripts import — Option B below
needs to say which, not just "a package," once that's known.

### C — Same split, no new root: `ansible/secrets/` alongside `ansible/cloud_credentials/`

Smaller move, no new top-level directory — but keeps standalone,
non-Ansible Python tooling nested under a directory named for Ansible
specifically, arguably the same kind of naming mismatch this draft
exists to fix (none of this code is a role or a plugin).

## Decision

Not yet — itemized for later review, no lean recorded until scoped.

## Assumptions (todo, unchecked)

- Every reference to `cloud_credentials.` as an import path or
  `python3 -m cloud_credentials....` as an invocation string needs
  enumerating before a move is safe — `cloud-credential-creation.md`'s
  own command examples, CI's `python-unit-tests` job, any systemd unit
  `ExecStart` referencing a module path, and
  `ansible/tests/cloud_credentials/`'s directory mirroring. Not
  enumerated yet.
- Whether `r2_read_watcher.py` can move out of `docker/openbao/watcher/`
  without complicating its container build (Dockerfile `COPY` paths,
  etc.) — unchecked.
- Whether a `tools/` root needs its own `pyproject.toml`/dependency
  group separate from `ansible/`'s existing one, or can share it — this
  repo's current single-`pyproject.toml`-under-`ansible/` shape isn't
  yet confirmed compatible with a sibling `tools/` root.

## Consequences

Once scoped, the actual move (broken imports, CI paths, systemd units)
is real multi-file mechanical work with regression risk — that becomes
its own project doc for tracking, separate from this decision of
whether/how to do it at all.
