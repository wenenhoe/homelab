# Scope boto3 to single-object Python calls, never the bulk-copy path

**Status:** Draft

## Context

`rclone` appears at five real call sites, in two structurally different
shapes:

- **Bash, containerized, bulk-copy:** `cloud_sync`'s `run.sh.j2` (the
  production job — `rclone copy seaweedfs:<bucket>/<path>
  <target>:<bucket>/<path>` per job in `/jobs.txt`), `openbao_backup`'s
  `snapshot-push.sh.j2`, and `backup_agent`'s `check-freshness.sh.j2` —
  all POSIX `sh`, all running `rclone` inside a pinned
  `rclone/rclone:1.75` container via `docker run`.
- **Python, single-object:** `cloud_credentials/verify.py`'s
  `lsjson`/`copyto` against a tiny marker object, and
  `restore_all.py`'s `rclone_lsjson`/`copyto` — one `lsjson` per
  discovery attempt, one `copyto` per app being restored. Both shell
  out via `subprocess`, never touching S3 credentials as Python values
  — `restore_all.py`'s own module docstring states this directly:
  *"This never touches GPG/SeaweedFS/cloud credentials directly in
  Python — it shells out to `rclone`... and to `gpg`."*

The bulk-copy sites aren't a boto3 candidate for one decisive reason,
not two as originally framed: `cloud_sync`'s `rclone copy` specifically
*is* the security control
[ADR 0010](../0010-cloud-sync-copy-not-sync.md) documents — the
guarantee that a compromised on-prem host can't touch the offsite copy
comes from `copy`'s own never-overwrite/never-delete semantics, not
from IAM scoping alone. Reimplementing that in hand-rolled boto3 calls
means re-deriving and re-proving that property instead of relying on a
well-known command. "They're not Python" is *not* an independent reason
on its own — see the next section for why that framing doesn't hold up.

## A separate axis: wrapper language, not just client library

The exclusion above is about *client library* (rclone's CLI semantics
vs. hand-rolled boto3 calls) — it says nothing about *implementation
language*. Rewriting `run.sh.j2`/`snapshot-push.sh.j2`/
`check-freshness.sh.j2` as Python wrappers that still shell out to the
same `rclone` binary via `subprocess` — exactly the pattern `verify.py`
and `restore_all.py` already use — is a genuinely separate, live
option: real exception handling and this repo's own JSON/YAML
libraries in place of `sh`'s `read`/`case` parsing of `/jobs.txt`,
while preserving `rclone copy`'s ADR 0010 semantics exactly as today,
since the binary being invoked doesn't change. This is not the same
proposal as swapping to boto3 — a Python wrapper around the same
`rclone copy` call carries none of the re-derive-the-security-property
risk above.

Not decided here — it changes deployment shape (today: `docker run
rclone/rclone:X.Y.Z <cmd>`, a container with no Python interpreter; a
Python wrapper needs one added, or a different container entirely) and
needs its own check before it's more than a plausible idea: whether
adding a Python interpreter to the pinned `rclone/rclone` image (or
building a thin wrapper image) is worth the added image-maintenance
cost against three POSIX-`sh` scripts that are currently short and
already well-commented. Worth scoping as its own draft once someone's
ready to spike it, rather than deciding by extension here.

Third-party rclone wrappers (`rclone_python`, `py-rclone`, etc.) were
considered separately and rejected regardless of which option below
wins: they still shell out to the same CLI underneath (no wire-format
drift they'd remove), don't carry this repo's own propagation-window
retry logic, and — unlike `boto3` or the SDKs in the sibling
`cloud_credentials` draft — aren't vendor/canonical, just a single
maintainer's project sitting in a credential-verification/restore
path. `rclone`'s own Remote Control (RC) API would be a genuinely
different transport, but means a standing daemon and an auth token to
secure, for scripts that run a handful of times per quarter — not
worth it at this scale.

The two Python sites are genuine candidates on the "does an official
SDK reduce risk" question `cloud-credentials-selective-sdk-adoption-not-blanket-swap.md`
already applies elsewhere — but they carry the credentials-in-process
trade the docstring above calls out, which needs its own decision, not
an assumption inherited from the other drafts. Both already handle
subprocess failure reasonably: `restore_all.py`'s `_run_rclone` catches
`subprocess.TimeoutExpired` and folds it into "treat this remote as
unreachable"; `verify.py`'s retry loop doesn't (tracked as its own
Stage 1 bug fix in
[`cloud-credentials-hardening.md`](../../projects/cloud-credentials-hardening.md),
independent of this decision).

## Options

### A — Adopt boto3 for both Python single-object sites

`verify.py` and `restore_all.py` both do plain `list_objects_v2`/
`put_object`/`get_object`-shaped work against S3-compatible endpoints —
boto3 is a natural fit for the operation shape, is AWS's own SDK
(widest possible maintenance guarantee of anything considered so far),
and removes two more `subprocess` calls this repo has to reason about.
Cost: `restore_all.py`'s stated design (credentials never enter this
script's own Python process) is given up, not preserved — the
access/secret key becomes a real client-constructor argument instead
of a path handed to an external binary.

### B — Leave both on rclone

Preserves the credentials-out-of-process design intact everywhere it
exists today, and keeps exactly one S3-compatible client
(`rclone.conf`) across every part of this repo that talks to
B2/R2/OCI/SeaweedFS — one place to apply the config-requirement
findings in `cloud-credential-creation.md` (`no_check_bucket`,
explicit `region`, endpoint scheme), rather than re-deriving them once
for rclone's backend and again for boto3's. Cost: keeps two
`subprocess`-based S3 clients in Python code that a direct SDK call
could otherwise remove.

### C — Adopt boto3 only where the credentials-in-process trade is already accepted

`verify.py` runs as part of `create_leaf_keys.py --rotate`, which
already holds the freshly-minted access/secret key as a Python value
(it just minted it) before ever handing it to `rclone` via a
temporary, single-use `rclone.conf` — so the "never touches credentials
directly in Python" property doesn't actually hold for `verify.py`
today the way it does for `restore_all.py`. Moving `verify.py` to boto3
gives up nothing that isn't already given up; moving `restore_all.py`
does. Split the decision instead of treating the two sites as one.

## Decision

Leaning Option C, pending the Assumptions below: `verify.py` → boto3,
`restore_all.py` stays on `rclone`. Not yet promotable — the first
Assumption needs a real check before this is more than a plausible
read of `verify.py`'s existing credential handling.

## Assumptions

- **Claim:** `verify.py`'s credential handling today already holds the
  access/secret key as a Python value before it ever reaches
  `rclone.conf`, so boto3 doesn't newly expose anything.
  **Breaks if wrong:** if the calling code (`create_leaf_keys.py`'s
  `--rotate` flow) receives the new key only as an opaque value it
  immediately writes to disk without holding a live reference, the
  "already given up" framing in Option C is incorrect and `verify.py`
  deserves the same caution as `restore_all.py`.
  **Checked by:** reading `create_leaf_keys.py --rotate`'s call path
  into `verify_leaf_via_rclone`, confirming where the key value lives
  between minting and the `rclone.conf` write, before Stage building
  starts.
- **Claim:** boto3's S3 client, pointed at each provider's
  `endpoint_url`, reproduces the same request shape rclone's S3 backend
  does for the specific calls in play (`HeadObject`-before-write on B2,
  `region` handling on OCI, `region=auto` on R2).
  **Breaks if wrong:** if boto3's default request behavior differs
  (e.g., a different pre-flight check than rclone's `HeadObject`),
  the hard-won findings in `cloud-credential-creation.md` need
  re-verifying per provider, not assumed to carry over.
  **Checked by:** a spike running boto3's `put_object`/`list_objects_v2`
  against a real bucket on each of B2/R2/OCI with the actual leaf
  credentials, diffed against `rclone`'s current behavior.
- **Claim:** boto3's own retry/timeout configuration can be tuned to
  match `verify.py`'s intentional propagation-window retry (broad,
  slow, ~15 minutes) without fighting boto3's default retry mode.
  **Breaks if wrong:** boto3's built-in retries (`standard`/`adaptive`
  modes) aren't designed for "keep retrying a 403 for 15 minutes
  because the key hasn't propagated yet" — if they can't be disabled
  cleanly in favor of this repo's own loop, the swap adds complexity
  instead of removing it.
  **Checked by:** the same spike above, explicitly exercising the
  propagation-window retry path (a real just-minted, not-yet-propagated
  key), not just a happy-path call.

## Consequences

- `cloud_sync`, `snapshot-push.sh.j2`, and `check-freshness.sh.j2` stay
  on `rclone` regardless of this decision's outcome — not because they
  weren't considered, but because they're bash/containerized and
  `cloud_sync`'s in particular is load-bearing for
  [ADR 0010](../0010-cloud-sync-copy-not-sync.md). Re-raising a boto3
  swap for these specifically should point back here rather than being
  re-litigated from scratch.
- If `verify.py` moves to boto3 and `restore_all.py` doesn't, this repo
  ends up with two different S3-compatible clients in Python code
  (`boto3` in one script, `rclone` via `subprocess` in the other) —
  accepted as a legitimate outcome of the credentials-in-process
  question landing differently for each, not an inconsistency to
  "fix" later.
- Either way, `verify.py`'s uncaught `subprocess.TimeoutExpired` (Stage
  1 of the hardening project) gets fixed before this decision matters —
  if boto3 replaces the `rclone` call entirely, that bug becomes moot
  rather than fixed.
- Swapping `rclone` for `boto3` doesn't *remove* a secret sitting on
  disk in the clear — it relocates which one. `rclone.conf` today holds
  real S3-compatible access/secret keys in plaintext (confirmed:
  `openbao_backup`'s own `RCLONE_CONF` path is a plain file on the host,
  mounted read-only into the container). A `boto3`+`hvac` combination
  needs its own long-lived auth material somewhere unless it's fetched
  fresh every run — an OpenBao token or AppRole `secret_id` on disk
  instead of S3 keys on disk is not obviously a win, just a different
  secret in the same kind of exposure. This is the same problem, one
  level up, as whatever gets decided for Secret Zero more broadly — not
  resolvable inside this draft alone.
