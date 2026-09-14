# Secret Zero: converge on one bootstrap pattern, or accept several

**Status:** Draft — exploratory, not scoped for building yet

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
  between logins — not fully traced in this pass.
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

## Directions raised, none evaluated yet

- **Trusted Orchestrator Pattern:** a single, tightly-controlled host
  or process holds the one long-lived credential and hands out
  short-lived, scoped ones to everything else — `controller` (per the
  `cd-agent.md` project) may already be conceptually close to this
  role; worth checking before inventing a new component. OpenBao's own
  **response wrapping** is the concrete, already-available mechanism
  for this — no new infrastructure needed, unlike mTLS/attestation
  below. Vault/OpenBao wraps a response (e.g. a freshly-generated
  `secret_id`) in a single-use, short-TTL token; the orchestrator
  relays only that wrapping token, never the real secret; the consumer
  unwraps it exactly once. A second unwrap attempt fails outright —
  turning a silent interception into an immediate, detectable failure
  instead of a quietly-stolen, reusable credential. This maps directly
  onto the real, already-documented next step in this repo: once
  `cd_agent` exists, it needs to authenticate as `controller`'s AppRole
  unattended (`docs/openbao-backup-restore.md`'s own "Open
  follow-ups"), and `cache.py`/`bootstrap_secrets.py`'s currently vague
  "entered by a human or read from wherever it's stored between
  logins" is exactly the gap wrapping would make concrete and
  auditable. It does **not** remove Secret Zero, though — the
  orchestrator (`controller`) still needs its own credential to Vault
  to request the wrapped response in the first place. Wrapping protects
  the second hop (orchestrator → new consumer), not the first
  (orchestrator → Vault); that first hop still needs its own answer,
  from this list or another one.
- **Local OS secret stores:** e.g. `systemd-creds`, a TPM-sealed
  secret, or an OS keyring — keeps the bootstrap credential out of a
  plain file at the cost of tying it to a specific host's hardware/OS
  facilities, which cuts against this repo's general preference for
  reproducible, re-creatable hosts.
- **Something else / accept the status quo as the deliberate answer:**
  formalize "a human types it in when needed" as the actual chosen
  pattern for low-frequency, high-sensitivity operations — but this
  would be a deliberate reversal of the documented plan (`cd_agent`
  automating this), not a continuation of an existing stance, per the
  correction above. Worth stating honestly as "stop planned automation
  here" if chosen, not "formalize what's already true."
- **mTLS via CA-issued certs:** doesn't eliminate Secret Zero, but
  shrinks it to a one-time event instead of a recurring one — this
  repo already demonstrates the split in `step_ca_cert`'s own task
  file: initial issuance "needs the JWK provisioner password, since
  there's no existing cert yet to authenticate with," but renewal
  forever after "uses mTLS against the cert this role just issued, so
  it never touches the provisioner password at all." Structurally
  better than a bearer secret too, if the private key is generated on
  the target host itself and only the CSR (public material) is sent
  for signing — the actual secret never has to be transmitted anywhere,
  unlike an AppRole `secret_id` or an S3 access key. Doesn't solve
  first-contact for a brand-new host: the provisioner password (or
  equivalent) still has to reach it once, by some other means — that
  delivery is the same open problem as every other direction here, not
  resolved by adding mTLS. The more complete answer to *that* piece is
  attestation-based issuance (SPIFFE/SPIRE-style: sign a CSR based on
  something intrinsic to the host — a TPM key, a cloud instance
  identity document — instead of a shared password), which removes the
  shared-secret delivery step entirely but is likely heavier
  operational weight than a handful of self-managed homelab hosts
  needs; worth naming as the ceiling, not assumed as the target.

## Why this probably isn't a small addition to an existing draft

Every other draft from this session that touches a credential
(`rclone-boto3-scope-not-blanket-swap.md`,
`openbao-client-hvac-paramiko-adoption.md`,
`tools-directory-and-secrets-package-split.md`) currently treats
"where does the credential live" as a local, per-file Assumption.
Resolving Secret Zero properly could change the answer for all of them
at once — which argues for scoping this as its own project once
someone's ready to spend real time on it, rather than deciding it as a
side effect of whichever draft gets picked up first.

## Not yet done

- Enumerate every credential-bootstrap point in the repo properly —
  this Context section is a first pass from what's already been read
  this session, not a real audit.
- Check whether `controller`/the `cd-agent` project already implements
  something Trusted-Orchestrator-shaped, before assuming a new pattern
  is needed.
- Decide whether this repo's threat model (single operator, homelab
  scale) even warrants solving this generally, versus formalizing the
  human-typed pattern as the deliberate answer for the few places that
  need it.
- If mTLS is the direction: whether `step_ca_cert`'s existing
  provisioner-password pattern is good enough to reuse as-is for
  OpenBao/cloud-credential bootstrap too, or whether those need their
  own enrollment flow — not assumed either way.
- If response wrapping is the direction: what `controller`'s own
  credential to Vault looks like once `cd_agent` needs to request
  wrapped responses on a schedule rather than a human doing it
  interactively — that's the first-hop problem wrapping doesn't solve,
  and it's the actual blocker on `cd_agent`'s AppRole automation, not
  a side detail.
