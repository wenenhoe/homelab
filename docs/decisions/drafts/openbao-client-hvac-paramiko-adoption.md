# Adopt hvac + paramiko for every internal OpenBao/SSH client, not just cloud_credentials

**Status:** Draft

## Context

`cache.py` (`ansible/cloud_credentials`) and `bootstrap_secrets.py`
each independently hand-roll an OpenBao AppRole login + KV v2
read/write over raw `requests`, and each independently fetches
step-ca's root cert via `ssh ... docker exec step-ca cat
root_ca.crt` as a raw `subprocess` call. `cache.py`'s own docstring
says the duplication is deliberate: `bootstrap_secrets.py` is "a
standalone top-level script, not part of the `cloud_credentials`
package" (per `ansible/tests/test_bootstrap_secrets.py`'s module
docstring), so its tests patch their own independent constants rather
than reaching into `cloud_credentials.cache`. That's a test-isolation/
packaging boundary — nothing in either file states a prohibition on
sharing a small internal helper.

The duplication has already produced the same bug twice, independently
confirmed in each file: neither `cache.py`'s nor `bootstrap_secrets.py`'s
SSH-fetch `subprocess.run` call sets a timeout, so an unreachable
`security` host or a network partition blocks either one forever.
Fixing one without the other leaves the second stale — exactly the
failure mode two genuinely independent copies of the same logic
produce over time.

Two more files share this surface: `audit_secrets.py` reads the same
OpenBao KV v2 paths (its `--local`/`--provider` diff logic, per
`cloud-credential-creation.md`) over its own `requests` calls, and it
also calls B2/OCI/R2's control-plane APIs directly — so it inherits
whatever `cloud-credentials-selective-sdk-adoption-not-blanket-swap.md`'s
OCI/B2 stages decide, not just this draft's Vault-client question.
`docker/openbao/watcher/r2_read_watcher.py` (ADR 0026) is
architecturally different from the other three: a standing,
continuously-running watcher, not a one-shot script a human or a
scheduled job re-invokes on failure. A hang or an uncaught exception
here is a silent alerting gap, not a single failed run someone notices
and re-runs.

This draft supersedes
[`cloud-credentials-selective-sdk-adoption-not-blanket-swap.md`](cloud-credentials-selective-sdk-adoption-not-blanket-swap.md)'s
original `cache.py`/`hvac`/`paramiko` Decision and Assumptions — that
draft is trimmed back to what's actually specific to
`ansible/cloud_credentials` (OCI SCIM, B2, R2, `oci_iam.py`), cross-
referencing here for the Vault-client question instead.

## Options

### A — Each file keeps its own independent `hvac`/`paramiko` usage

Preserves the standalone-script boundary exactly as it exists today —
no new shared module, no new inter-file dependency. Cost: the same fix
(or the next one) still needs applying by hand in up to four places;
the exact failure mode that motivated this draft — one file getting a
fix the other didn't — can recur.

### B — Extract a small shared internal helper (e.g. `ansible/lib/openbao_client.py`) once two or more callers need the identical logic

Removes the duplication at its root. `bootstrap_secrets.py`'s stated
reason for independence is about not reaching into `cloud_credentials`'s
own package internals for test isolation — not a blanket rule against
sharing any code at all — so a small, deliberately separate helper
module doesn't obviously conflict with it. Cost: this repo has no
precedent for a shared internal library living outside an Ansible role
or the `cloud_credentials` package itself; introducing one is a real
(if small) architecture decision, and needs its own test suite, with
both callers' existing tests moving their mock boundary to it.

### C — Fix each file independently now, revisit sharing only if a third instance of the same bug appears

Smallest step, and matches this repo's general preference for not
building shared infrastructure ahead of a proven, repeated need. Cost:
explicitly accepts the duplication — and its bug-recurrence risk — as
a known, named trade-off rather than an oversight.

## Decision

Leaning Option B, given the bug has already recurred once independent
of any change here — but not promotable until the Assumptions below
are checked. Regardless of A/B/C, `r2_read_watcher.py` gets its own
stage: a standing process has a different risk profile (reconnect,
token renewal before expiry) that a one-shot script's spike won't
surface.

## Assumptions

- **Claim:** a shared helper module wouldn't violate
  `bootstrap_secrets.py`'s stated independence — that independence is
  about test isolation from `cloud_credentials`'s internals, not a
  prohibition on sharing any code.
  **Breaks if wrong:** if there's an unstated reason beyond what
  `test_bootstrap_secrets.py`'s docstring says — e.g. this script must
  keep working even if `cloud_credentials`'s own package fails to
  import — a shared module could reintroduce a dependency this repo
  deliberately avoided.
  **Checked by:** re-reading every reference `cache.py`'s docstring
  points to in full (not just the one line already found) before any
  Stage 5-equivalent (shared module) work starts.
- **Claim:** `hvac`'s AppRole login + custom-CA-verify model fits both
  files' SSH-fetched-root-cert session pattern without restructuring
  either one's session-reuse/cleanup design.
  **Breaks if wrong:** if `hvac`'s client construction or session
  internals don't compose with a per-process temporary CA file the way
  today's fetch-then-login pair does in each file, this becomes a
  larger restructure than a like-for-like client swap, in both places.
  **Checked by:** a throwaway spike logging into a real OpenBao
  instance via `hvac.Client(url=..., verify=ca_path)` +
  `auth.approle.login()`, before Stage 1 is built for real.
- **Claim:** `paramiko` reproduces both files' current trust behavior
  (`StrictHostKeyChecking=accept-new`'s trust-on-first-use) and
  `docker exec ... cat ...` semantics over an exec channel, without
  weakening a security-relevant default.
  **Breaks if wrong:** if `paramiko`'s host-key handling doesn't map
  cleanly onto today's explicit CLI flag, swapping clients here could
  silently loosen (or overly tighten, breaking the run) host-key trust.
  **Checked by:** a spike connecting to a real `security` host with
  `paramiko`, confirming host-key behavior and that its exec channel
  returns the same cert bytes `ssh ... docker exec ... cat` does today.
- **Claim:** `r2_read_watcher.py`'s standing-process shape needs only
  the same client as the one-shot scripts, kept alive/reconnecting,
  not a fundamentally different design.
  **Breaks if wrong:** if a long-lived watcher needs token renewal
  before expiry or reconnect-with-backoff that a one-shot script's
  spike wouldn't exercise, this file needs its own spike, not
  inheritance from the others.
  **Checked by:** a dedicated spike keeping an `hvac` session alive
  across a simulated OpenBao restart/token expiry.

## Consequences

- Trims `cloud-credentials-selective-sdk-adoption-not-blanket-swap.md`
  back to OCI/B2/R2/`oci_iam.py` — its Vault-client content moves here.
- If Option B wins, `cache.py`'s and `bootstrap_secrets.py`'s existing
  tests both move their mock boundary to the new shared module.
- `audit_secrets.py`'s Vault-side stage should land in step with
  whichever this draft picks, but its provider-API stages (OCI/B2)
  need to stay in step with the sibling `cloud_credentials` draft
  instead — two different dependencies for one file.
- `r2_read_watcher.py`'s stage lands independently of A/B/C above,
  given its distinct standing-process risk profile.
