# Secret Zero: converge on one bootstrap pattern, or accept several

**Status:** Draft — exploratory, not scoped for building yet

## Context

This repo currently has at least three different, independently-arrived-at
answers to "how does the first credential get to a process that needs
it":

- **Human-typed, per-run:** `snapshot-push.sh.j2` requires a human to
  `export BAO_TOKEN` in their own shell before running it by hand — a
  deliberate choice, per its own comment, specifically to avoid the
  token ever living in a file or a systemd unit
  (`docs/openbao-backup-restore.md` has the fuller reasoning).
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
  role; worth checking before inventing a new component.
- **Local OS secret stores:** e.g. `systemd-creds`, a TPM-sealed
  secret, or an OS keyring — keeps the bootstrap credential out of a
  plain file at the cost of tying it to a specific host's hardware/OS
  facilities, which cuts against this repo's general preference for
  reproducible, re-creatable hosts.
- **Something else / accept the status quo deliberately:** formalize
  "a human types it in when needed" (already true for
  `snapshot-push.sh.j2`) as the actual chosen pattern for
  low-frequency, high-sensitivity operations, rather than a workaround
  waiting to be automated away.

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
