# 0021. Manual Shamir unseal, not cloud auto-unseal

**Status:** Accepted

## Context

[0017](0017-openbao-bootstrap-secret-split.md) left the unseal method
itself open, noting cloud auto-unseal's own credential would need the
same offline handling it exists to avoid. The remaining question was
practical, not architectural: does `security` reboot often enough that
manual Shamir unseal becomes a real recurring chore, justifying that
extra dependency anyway?

Confirmed live on `security`: automatic reboot-after-update is
disabled, so this host does not reboot itself for package updates —
every reboot requires a human to trigger it. Its reboot history over
the preceding two months shows exclusively operator-initiated
reboots, clustering around active maintenance sessions rather than any
unattended or scheduled pattern, and the current uptime is the longest
stretch on record — not an outlier against the rest of the history.

The failure mode manual unseal is genuinely bad at — a host rebooting
unattended overnight, sealed and unreachable until someone notices —
doesn't occur on this host: every reboot recorded is operator-driven,
meaning a human is already present at the exact moment an unseal
prompt would appear.

## Decision

Use manual Shamir key shares for OpenBao's unseal, not cloud
auto-unseal. No new external cloud-KMS dependency, no second offline
recovery credential beyond what
[0017](0017-openbao-bootstrap-secret-split.md) already introduces.

## Consequences

- Every reboot of `security` — planned maintenance, a kernel update
  applied by hand, hardware work — needs a human to supply unseal
  shares before OpenBao serves anything again. Given the confirmed
  reboot pattern above, this cost lands at the same moment the
  operator is already at the keyboard, not as a surprise later.
- If `Automatic-Reboot` is ever turned on, or `security`'s role changes
  such that unattended reboots become normal, this decision's premise
  no longer holds and should be revisited — auto-unseal exists
  specifically for the scenario this ADR just confirmed doesn't apply
  here today.
- No dependency on any of R2/B2/OCI (or another cloud provider) for
  OpenBao's own availability — sealing/unsealing has zero interaction
  with the cloud credentials this migration is otherwise moving into
  Vault.
