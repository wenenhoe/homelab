# OpenBao Python Client Hardening

**Status:** Not started

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
| 1 | `cache.py` → `hvac` + `paramiko` | Not started |
| 2 | `bootstrap_secrets.py` → same swap | Not started |
| 3 | `audit_secrets.py`'s Vault calls → `hvac` | Not started |
| 4 | `r2_read_watcher.py` → `hvac`, plus its own reconnect/token-renewal spike | Not started |
| 5 | Extract a shared helper module (only if the draft's Option B wins) + re-baseline stage 1/2's tests against it | Not started |

## Stage detail

### Stage 1 — `cache.py` → `hvac` + `paramiko`

Blocked on the decision draft's `hvac` and `paramiko` Assumptions.
Every leaf/rotation module in `ansible/cloud_credentials/` reads and
writes exclusively through `cache.py`'s `scoped()`, so
[`cloud-credentials-hardening.md`](cloud-credentials-hardening.md)'s
stages inherit this stage's error-handling improvement once it lands —
tracked here, not duplicated as a stage in that project.

### Stage 2 — `bootstrap_secrets.py` → same swap

Same Assumptions as Stage 1 — confirmed to be the identical gap
(missing SSH timeout, hand-rolled Vault client), so this stage is
"apply Stage 1's proven pattern here," not a separate evaluation.
Whether this lands as independent code (Option A) or through a shared
module (Option B) is the draft's open question, not decided per-stage.

### Stage 3 — `audit_secrets.py`

Its Vault-side calls follow Stage 1/2's pattern. Its B2/OCI provider
calls are a different dependency: they should move in step with
[`cloud-credentials-hardening.md`](cloud-credentials-hardening.md)'s
OCI/B2 stages instead, so this file doesn't end up on a different SDK
than the scripts it audits.

### Stage 4 — `r2_read_watcher.py`

Standing process, not a one-shot script — needs its own spike
(reconnect-with-backoff, token renewal before expiry) rather than
inheriting Stage 1's one-shot-script spike. Independent of whichever
option (A/B/C) the draft settles on for the other three files.

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
