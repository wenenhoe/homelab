---
id: EXP-cloud-credential-custody
title: "How could the credentials that mint and revoke the cloud keys be kept away from the host that runs the secrets store?"
type: exploration
status: open
summary: "Whether the rotation credentials can sit offline between rotations, as an offline root CA does, so a compromised secrets host yields no way to mint a cloud write key."
topic: cloud-credentials
related: [ADR-0006, ADR-0109, ADR-0110]
---

# How could the credentials that mint and revoke the cloud keys be kept away from the host that runs the secrets store?

[ADR 0006 (Offsite backup credentials)](../decisions/0006-offsite-backup-credential-blast-radius/revision-000.md)
keeps cloud credentials off every app host, and `security` is an app host that
also runs OpenBao, which holds the cloud write keys and the three credentials that
create and revoke them
([`backup-threat-model.md`](../topics/disaster-recovery/backup-threat-model.md)).
Moving only the write keys out of OpenBao would not close that: a host that holds
a rotation credential can mint itself a new write key. The question is where the
rotation credentials can live so that holding the secrets store is not enough.

## What bears on it

- Every leaf key and every rotation credential expires after 90 days
  ([ADR 0109 (Cloud credential expiry)](../decisions/0109-knowing-a-cloud-credential-is-about-to-expire/revision-000.md)).
  A rotation credential is therefore used at most every few weeks, by a person,
  from the controller (`rotate_leaf_keys`), and by nothing unattended.
- What runs unattended needs far less. `cloud_sync` needs the write key on
  `storage`. A restore needs the read key. The weekly expiry check reads only key
  identifiers from OpenBao and looks each key up with a rotation credential
  (`check_credential_expiry.py`); it never uses a leaf secret.
- The write key already travels from OpenBao through Ansible into `storage`'s
  `rclone.conf`, so the key on `storage` is a copy and OpenBao is the source.
- B2 and OCI let the repository mint a narrow rotation delegate; R2 does not, and
  its admin token is master-equivalent and alerted on every read
  ([ADR 0110 (R2 admin token custody)](../decisions/0110-the-r2-admin-token-as-the-rotation-credential/revision-000.md)).
  The R2 rotation credential has an interactive prompt path already, used when
  it is absent from OpenBao.
- The model is an offline root CA: the root key stays off the network and signs a
  few times a year, and an online intermediate does the daily signing and is
  revoked and reissued by the root when it is lost. The rotation credentials
  play the root, the leaf write key on `storage` the intermediate.
- OpenBao is planned to unseal itself from a cloud KMS key
  ([ADR 0018 (Secrets store unsealing)](../decisions/0018-unsealing-the-secrets-store-after-restart/revision-001.md),
  `working`). A second instance meant to stay closed would keep manual unsealing.
- To be checked for each provider: whether a credential that can read key
  expiry and nothing else exists. B2 application keys have a list-only
  capability. Whether an R2 token can read a token's expiry without being able to
  edit tokens, and which OCI domain role can read a customer secret key without
  creating one, have not been looked at.

## Options

The rotation credentials' home is the choice. Each option below also assumes the
same two companions, set out after the list.

- **Held by the maintainer, typed at the rotation.** The rotation credentials
  are in the maintainer's password manager and entered at a prompt on the
  controller, then dropped, as R2's fallback prompt already does. Nothing online
  holds them. It costs a hand step every rotation, and the credential rotates
  itself in the same sitting: a Console step for R2, a regeneration for OCI, a
  key mint for B2. A lost password manager entry means the provider's Console
  recovery.
- **A second OpenBao that stays sealed.** A separate instance holds the rotation
  credentials, runs with manual Shamir unsealing and is unsealed only for the
  rotation, so the data at rest is unreadable to a host that is merely running.
  It reads the same credentials with the same tooling the repo has, and keeps the
  alert on every read. It adds a service to maintain, a set of shares to keep and
  a host to put it on: `storage` is outside the adversary, but it is the smallest
  host and would then hold both the archives and their keys; the operator host
  is the other candidate.
- **Hardware-backed.** A token or HSM holds the credentials. The providers issue
  bearer tokens and keys that cannot be generated inside a device, so the
  device would only guard a file. It is not an improvement over the two above.
- **Leave them in OpenBao.** The accepted risk today, with a review date and an
  ADR 0006 revision to say so. Cheapest, and the offsite copy then rests on the
  provider lock alone if `security` falls.

Companions to every option but the last:

- **An expiry-only credential per provider** stays in OpenBao for the weekly
  check, where the provider offers one. The check then reads every leaf and the
  rotation credential's own expiry without a credential that can write. Where it
  does not, the rotation credential's expiry is a stored timestamp, as OCI's
  already is.
- **The write key reaches `storage` without OpenBao holding the secret.** The
  rotation hands the new key straight to `storage`, and OpenBao keeps its
  identifier only. On `storage` it is a root-only file as now, a systemd
  credential encrypted to the host, or a small local store. Each keeps the key
  on a host the model already trusts. A rebuilt `storage` has no key, so the
  rotation runs and revokes the old one.

What a compromised `security` would yield, by option: today, a way to mint a write
key at every provider. With the rotation credentials offline or sealed and the
companions in place, key identifiers and a credential that lists keys, which
cannot write, mint or delete.

## Leaning

None yet. The maintainer-held option needs no new service and matches a rotation
that happens a few times a year, so it is the first to try; the sealed instance
is worth the extra service only if typing the credentials proves too error-prone
or too slow. The provider checks above decide whether the expiry-only credential
is possible at R2 and OCI, and the answer shapes the companions more than the
choice between the two. Plaintext secrets on hosts beyond the cloud credentials
are a wider question this does not take on.
