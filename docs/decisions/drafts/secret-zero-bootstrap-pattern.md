---
id: DRAFT-secret-zero-bootstrap-pattern
title: "Secret Zero: mTLS for controller's own auth, response wrapping for one-time handoff"
type: draft-adr
status: draft
---

# Secret Zero: mTLS for controller's own auth, response wrapping for one-time handoff

**Status:** Draft — leaning design reached, not yet spiked

## Context

This repo currently has at least three different, independently-arrived-at
answers to "how does the first credential get to a process that needs
it":

- **Human-typed, per-run:** `snapshot-push.sh.j2` requires a human to
  `export BAO_TOKEN` in their own shell before running it by hand.
  Confirmed against `docs/openbao-backup-restore.md` directly, not
  assumed: this is an explicit stopgap, not a permanent choice — the
  doc states outright that it "proves the mechanism with a human
  running it interactively... for now," pending the
  [CD agent project](../../projects/cd-agent.md)'s `cd_agent` host,
  "not built yet." Whatever replaces it needs its own answer to this
  same Secret Zero question, not a continuation of the human-typed
  pattern.
- **AppRole `role_id`/`secret_id`:** `cache.py`, `bootstrap_secrets.py`,
  and `docker/openbao/scripts/bao-login.sh` all bootstrap OpenBao
  access via AppRole, with `secret_id` handled carefully (hidden
  prompt, temp file inside a container, deleted immediately) but
  ultimately entered by a human or read from wherever it's stored
  between logins — not fully traced yet.
- **Plaintext config on disk:** `rclone.conf` holds real B2/R2/OCI
  access/secret keys in the clear, mounted into containers as needed
  (`cloud_sync`, `openbao_backup`, `restore_discovery`).
- **SSH private keys:** `cache.py`/`bootstrap_secrets.py`'s
  `_fetch_root_cert`/equivalent both rely on an SSH key to reach
  `security` in the first place.

None of these is wrong in isolation — each was a reasoned choice for
its own script. But
[`rclone-boto3-scope-not-blanket-swap.md`](rclone-boto3-scope-not-blanket-swap.md)'s
Consequences already ran into this from a different angle: swapping
`rclone` for `boto3`+`hvac` doesn't remove a secret sitting on disk, it
relocates which one. That's the actual Secret Zero problem surfacing
again, not a new one — this repo has multiple ad hoc partial answers
and no single deliberate one.

## Directions raised, now converged into a leaning design

Checked directly against `cd-agent.md`, not assumed: the actual planned
design is **not** an ongoing Trusted-Orchestrator-relays-everything
model. `cd_agent` gets its **own** CIDR-bound AppRole (Stage 2:
`cd-agent-deploy`/`cd-agent-rotation`, no shared access between them) —
`controller` doesn't hand it credentials on a recurring basis.
Stage 3 goes further: it retires `controller`'s own standing AppRole
outright, so that "any admin/debug access mints a fresh, narrow,
short-lived token on demand instead." That's already a better shape
than a perpetual orchestrator — but the project doc doesn't say *how*
`controller` authenticates to do that on-demand minting without a
standing credential of its own. That's the real, concrete gap this
draft converges on.

- **mTLS closes that exact gap.** `controller` gets a step-ca-issued
  client cert — the identical provisioner-password-once,
  mTLS-renewal-forever pattern `step_ca_cert` already proves live —
  and authenticates to OpenBao via Vault's `cert` auth method instead
  of holding an AppRole. Nothing standing sits on `controller`'s disk
  between uses; every on-demand token mint is backed by a
  short-lived, renewable certificate instead of a static secret. Not
  confirmed: whether OpenBao supports the `cert` auth method the same
  way Vault does — very likely, given how broadly API-compatible it
  is, but not verified live.
- **Response wrapping handles the one remaining real gap: provisioning
  `cd_agent` itself.** Not an ongoing relay — `cd_agent` uses its own
  AppRole directly and repeatedly after this — just the single,
  one-time handoff of its freshly-minted `secret_id` at build time.
  `controller` (now mTLS-authenticated, per above) requests a wrapped
  response for that `secret_id`; whoever provisions `cd_agent` unwraps
  it exactly once. A second unwrap attempt fails outright, turning a
  silent interception into an immediate, detectable failure instead of
  a quietly-stolen, reusable credential. This also gives
  `cache.py`/`bootstrap_secrets.py`'s currently vague "entered by a
  human or read from wherever it's stored between logins" a concrete,
  auditable answer for the same class of moment.

Two directions considered and set aside, not because they're wrong,
but because the above already answers the actual planned architecture
more directly:

- **Local OS secret stores:** e.g. `systemd-creds`, a TPM-sealed
  secret, or an OS keyring — keeps the bootstrap credential out of a
  plain file at the cost of tying it to a specific host's hardware/OS
  facilities, which cuts against this repo's general preference for
  reproducible, re-creatable hosts.
- **Something else / accept the status quo as the deliberate answer:**
  formalize "a human types it in when needed" as the actual chosen
  pattern — but this would be a deliberate reversal of the documented
  plan (`cd_agent` automating this), not a continuation of an existing
  stance, and the mTLS+wrapping combination above already gives that
  automation a real mechanism instead of requiring a reversal.

Attestation-based issuance (SPIFFE/SPIRE-style: sign a CSR based on
something intrinsic to the host instead of a shared password) remains
the theoretical ceiling above mTLS+wrapping, named for completeness —
likely heavier operational weight than a handful of self-managed
homelab hosts needs, not assumed as the target.

## Why this probably isn't a small addition to an existing draft

Every other draft that touches a credential
(`rclone-boto3-scope-not-blanket-swap.md`,
`tools-directory-and-secrets-package-split.md`) currently treats
"where does the credential live" as a local, per-file Assumption.
Resolving Secret Zero properly could change the answer for all of them
at once — which argues for scoping this as its own project once
someone's ready to spend real time on it, rather than deciding it as a
side effect of whichever draft gets picked up first.

## Not yet done

- Confirm OpenBao supports Vault's `cert` auth method the same way —
  the whole `controller`-side of this design depends on it; not
  verified live yet.
- Whether `step_ca_cert`'s existing provisioner-password pattern is
  good enough to reuse as-is for issuing `controller`'s own client
  cert, or needs its own enrollment flow.
- The actual mechanics of the one-time `cd_agent` provisioning handoff
  — what unwraps the wrapped `secret_id`, and over what channel (SSH,
  a provisioning script, something else) — not designed yet, just
  identified as the one remaining real gap.
- Whether this design should be written back into `cd-agent.md`
  Stage 3 directly (it currently just says "mints a fresh... token on
  demand" with no mechanism) once the `cert`-auth-method check above
  confirms it's viable.
