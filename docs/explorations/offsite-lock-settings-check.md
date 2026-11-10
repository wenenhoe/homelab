---
id: EXP-offsite-lock-settings-check
title: "How could the lab notice that an off-site bucket's lock or lifecycle setting is gone or shorter than it should be?"
type: exploration
status: open
summary: "Whether a check can read each cloud bucket's lock and lifecycle settings, given that the repo manages neither, and who runs it."
topic: backup-recovery
related: [ADR-0010, ADR-0081, ADR-0110]
---

# How could the lab notice that an off-site bucket's lock or lifecycle setting is gone or shorter than it should be?

[ADR 0010 (Offsite copy deletion)](../decisions/0010-preventing-homelab-side-deletion-of-offsite-copies/revision-000.md)
keeps the on-prem relay from deleting a landed object: `rclone copy` never
issues a delete, and the provider's lock stops anyone who holds the credential
and calls the delete API directly. The first is client behaviour. The second
holds only while the setting does, and the repo neither sets nor reads it. A
rule that is removed, shortened or not re-applied after an account change
leaves every job green. The question is how that is noticed.

## What bears on it

- The windows are set by hand in each console and recorded in
  [`cloud-sync.md`](../topics/disaster-recovery/cloud-sync.md): R2 29 days, B2
  28 days, OCI 3 days under an unlocked retention rule. Each lock sits strictly
  below its own delete-after.
- ADR 0010 keeps them provider-native on purpose: a homelab-side job that
  enforced retention would need delete access, which nothing on-prem is given.
- A read of a bucket's lock configuration may need more than the relay's write
  credential or the restore credential grants. What each provider's API asks for
  has to be checked.
- [`second-cloud-archive-window.md`](second-cloud-archive-window.md) also treats
  the settings as provider-native console state.

## Options

- **A scheduled read-only check.** A job on the CD agent reads each bucket's lock
  and lifecycle settings with a credential that can read them and write nothing,
  and alerts when one differs from the documented window. It needs a new
  credential per provider, and the settings' expected values would live in the
  repo for it to compare.
- **A step in the DR exercise.** The operator reads the three consoles at each
  exercise and compares them with the table. No credential and no code, but the
  interval is the exercise's, so a removed rule can sit unnoticed until then.
- **Declare the settings in code.** Tofu or the collection sets them, so a plan
  shows drift. It needs a credential that can change a bucket's lock, held
  wherever the apply runs, which ADR 0010 keeps away from on-prem hosts.
- **Leave it.** The failure needs a second event: a compromised relay credential
  while a lock is missing.
