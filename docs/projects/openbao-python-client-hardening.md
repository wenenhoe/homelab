---
id: PROJ-openbao-python-client-hardening
title: "OpenBao Python Client Hardening"
type: project
status: in-progress
summary: "`hvac` + `paramiko` adoption across every internal OpenBao/SSH client (`cache.py`, `bootstrap_secrets.py`, `audit_secrets.py`, `r2_read_watcher.py`), replacing duplicated hand-rolled clients."
---

# OpenBao Python Client Hardening

**Status:** In progress

Adopts `hvac` (and `paramiko` for the SSH root-cert fetch) across every
internal Python client that talks to OpenBao directly — currently
`ansible/cloud_credentials/cache.py`, `ansible/bootstrap_secrets.py`,
`ansible/audit_secrets.py`, and `docker/openbao/watcher/r2_read_watcher.py`
— replacing four independent (in two cases, already-diverged)
hand-rolled `requests`/`subprocess` implementations. Scope and
sequencing are decided in
[`openbao-client-hvac-paramiko-adoption.md`](../decisions/drafts/openbao-client-hvac-paramiko-adoption.md);
this doc tracks build status only.

## Stages

| # | Stage | Status |
| :-: | :--- | :--- |
| 1 | `cache.py` → `hvac` + `paramiko` | Done |
| 2 | `bootstrap_secrets.py` → same swap | Done |
| 3 | `audit_secrets.py`'s Vault calls → `hvac` | Done |
| 4 | `r2_read_watcher.py` → `hvac` | Done |
| 5 | Extract a shared helper module (only if the draft's Option B wins) + re-baseline stage 1/2's tests against it | Not started |

## Stage detail

### Stage 1 — `cache.py` → `hvac` + `paramiko`

Built, per the decision draft's confirmed `hvac`/`paramiko`
Assumptions (spikes run against the real OpenBao/`security` hosts).
Every leaf/rotation module in `ansible/cloud_credentials/` reads and
writes exclusively through `cache.py`'s `scoped()`, so
[`cloud-credentials-hardening.md`](cloud-credentials-hardening.md)'s
stages inherit this stage's error-handling improvement once it lands —
tracked here, not duplicated as a stage in that project.

### Stage 2 — `bootstrap_secrets.py` → same swap

Built independently, per Stage 1's proven pattern (same missing-SSH-
timeout gap, same hand-rolled Vault client, confirmed identical).
Diffing the two now that both exist: `fetch_root_cert()`'s body is
identical to `cache.py`'s `_fetch_root_cert()` apart from one
cross-referencing comment; `vault_read`/`vault_write`'s bodies are
identical to `cache.py`'s `_vault_read_at`/`_vault_write_at` apart from
taking an `hvac.Client` as an explicit parameter instead of pulling one
from `cache.py`'s process-lifetime session cache (this script makes far
fewer Vault calls per run, so it doesn't need one). This is the actual
evidence the Stage 5/Option B decision was waiting on — not a
projection anymore.

### Stage 3 — `audit_secrets.py`

Done, with no code change: `audit_secrets.py` never hand-rolled its
own Vault HTTP calls - its only Vault touch is `cached()`, which
delegates entirely to `LEGACY_CACHE_KEYS[name].read_cache(name)`
(`cache.py`'s `scoped()`, already `hvac`-based since Stage 1). Its
B2/OCI provider calls are a different dependency: they move in step
with [`cloud-credentials-hardening.md`](cloud-credentials-hardening.md)'s
OCI/B2 stages instead, so this file doesn't end up on a different SDK
than the scripts it audits.

### Stage 4 — `r2_read_watcher.py`

Done. The project doc's original premise for this stage - needing its
own reconnect-with-backoff/token-renewal spike, since it's a standing
process - didn't hold once the actual code was read: Vault login
happens once at startup to fetch Telegram's secrets, and `watch()`'s
long-running `docker logs -f` loop never receives or reuses that
token, so a token expiring hours or months later is irrelevant. No
SSH/paramiko either - this runs on `security` itself over loopback,
unlike `cache.py`/`bootstrap_secrets.py`.

The real risk here was different: this script runs under
`/usr/bin/python3` (system Python, hand-installed per
[`openbao-r2-read-watcher.md`](../openbao-r2-read-watcher.md), not the
`uv`-managed environment the rest of the repo uses), so `hvac` has to
be installed there separately. Confirmed live which package version
that actually gets: Ubuntu 26.04's (`security`'s release) `apt`
`python3-hvac` is 2.3.0, satisfying `pyproject.toml`'s `hvac>=2.3`
floor and already including `raise_on_deleted_version` - but the same
package is a much older 0.11.2 on 22.04/24.04, which predates that
parameter and would have failed at runtime. The install doc now
documents the `apt install python3-hvac` step and this version
constraint explicitly.

## Open items

- Whether Option A, B, or C wins — see the decision draft's
  Assumptions; each names its own check.
- Whether a shared module (if built) lives under a new `ansible/lib/`
  or elsewhere — not decided; only relevant if Stage 5 happens at all.
- Keeping `audit_secrets.py`'s provider-API stage in step with
  `cloud-credentials-hardening.md`'s Stages 2-3, so the two projects
  don't silently diverge on which SDK a given provider uses.
- The same duplication pattern this project exists to fix shows up a
  third time in Ansible task form, not just Python: `ansible/roles/secrets`'s
  3 Vault `uri` tasks and `molecule_helpers`' OpenBao CLI setup
  hand-roll the identical AppRole-login-and-KV-v2 logic again. Tracked
  as its own stage in
  [`ansible-collections-audit.md`](ansible-collections-audit.md)
  (`community.hashi_vault`, the same `hvac` this project adopts, just
  via an Ansible module instead of a Python import) — not folded into
  this project's own stages, since the calling convention is
  different, but worth building in step with Stage 1 rather than
  independently.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes) — run
before deleting this doc once every stage is Done.

- [ ] Every `Done` stage's rationale exists as a real ADR, or plainly
      didn't need one.
- [ ] Every `Done` stage's current behavior is in a topic doc.
- [ ] Every open item is resolved-and-promoted or moved to where it
      belongs next.
- [ ] Every cross-reference into this doc elsewhere in the repo is
      updated or removed.
