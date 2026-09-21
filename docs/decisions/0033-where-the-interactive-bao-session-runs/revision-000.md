---
id: ADR-0033
revision: 0
type: adr
title: Where the interactive bao session runs
solution: controller only; the SSH relay to security dropped
summary: Where bao_session.py runs, given a relay to security never had a working local half.
topic: repository-tooling
status: accepted
---

# 0033. bao_session.py stays local to controller, drops the never-working security path

**Status:** Accepted

## Context

This started as a different draft: relay `bao_session.py`'s interactive
session to `security` over `ssh -t` instead of `controller` keeping
its own native `bao`, on the reasoning that `security` already has
everything the session needs and `controller`'s copy was just a second
version pin to track. A real spike (from an actual `controller`
machine) confirmed the relay's interactive mechanics work correctly -
`ssh -t` forwards a foreground Ctrl-C and `SIGWINCH` resize correctly,
and passes the real exit code through - but also surfaced that an
unclean disconnect (`kill -9` on the local `ssh -t` process) does
**not** run the relayed process's cleanup: `sshd` sends `SIGHUP` to the
whole remote process group, and Python's default disposition for
`SIGHUP` is immediate termination, bypassing `try`/`finally` entirely.
Confirmed live with a file-based execution log (to rule out the
pty simply dying before a print could land) - only "SESSION START"
was ever written, never the `finally` block's own line.

Fixing that (an explicit `SIGHUP` handler) was going to be part of
this decision regardless of which host runs the session. But a second
check, prompted by realizing `bao_session.py`'s own docstring claim of
being "usable from either `security` or `controller`" had never
actually been verified, invalidated the relay's premise entirely:

- **`security` doesn't have this repo checked out.** `bao_session.py`
  is a module inside the `tools/` package (imports `utils.repo`,
  `openbao_utils.client`), not a standalone script the way the old
  `bao-login.sh` was. Every doc claiming it already runs "from either
  `controller` or `security`" (`openbao-reinit-runbook.md`,
  `openbao-vault-bootstrap.md`) was describing a code path that never
  functioned - inherited from `bao-login.sh`'s era, when that really
  was true for a single scp'd shell script, and never re-verified once
  `bao_session.py` replaced it with a package-internal module.
- **`controller`'s native `bao` can't be dropped anyway.**
  `tools/openbao_utils/scripts/snapshot-push.sh` (Stage 5, already
  shipped) calls the local `bao` binary directly - `bao write`, `bao
  kv get`, `bao operator raft snapshot save` - dialing OpenBao's API
  over the network from `controller` itself, entirely independent of
  `bao_session.py`. Checked directly: it's the only other caller of a
  *local* `bao` binary in this repo: `init_unseal.py`'s two `bao
  operator` calls both go through `docker exec` on `security` over
  paramiko, no local binary involved. So the relay's stated
  benefit - "`controller` sheds an install step and a version pin
  entirely" - was never true; `snapshot-push.sh` needs that install
  regardless of what `bao_session.py` does.

With the install staying either way, the relay bought nothing but an
`ssh -t` process to reason about and a new interactive-PTY surface to
keep correct going forward, for a friction (two things checking one
version pin instead of one) real but too small to justify that.

## Decision

`bao_session.py` runs on `controller` only, unchanged in that respect
from its current shipped behavior - the local-vs-SSH auto-detection
(`_local_root_cert`, `get_root_cert`, `--controller`) is removed
outright rather than kept as dead branching, since the "local"
half of it never had anywhere to actually run. `fetch_root_cert()`'s
existing SSH fetch (ADR 0022's mechanism) is now unconditional.

An explicit `SIGHUP` handler is installed on the session (alongside
the existing `try`/`finally`/`KeyboardInterrupt` handling): on
`SIGHUP` it runs the same revoke-and-cleanup path, then exits, instead
of relying on Python's default disposition. The cleanup itself
(`_revoke`/`_cleanup`) is idempotent - clearing `client.token` after a
first attempt, confirmed live against `hvac.Client`'s own `token`
property (a trivial passthrough to the adapter, safe to set `None`) -
so both the signal handler and the ordinary `finally` block can reach
it for the same session without a spurious second revoke attempt.

Every doc claiming `bao_session.py` (or its retired predecessors)
"runs from either `controller` or `security`" is corrected to
`controller` only.

`controller`'s native `bao` install (`README.md`'s Setup section)
stays exactly as it is today - it's load-bearing for
`snapshot-push.sh` independent of this decision.

## Consequences

- `bao_session.py` loses a code path that never worked, not one that's
  being taken away - no functional regression for anyone, since it
  never functioned on `security` to begin with.
- The `SIGHUP` gap this surfaced closes for the only place the session
  actually runs; no relay-specific edge cases (mid-session network
  partition, PTY resize forwarding, argv-based token exposure over a
  second SSH hop) needed solving, since there's no second hop.
- `controller` keeps carrying a version-pinned `bao` install
  indefinitely, for `snapshot-push.sh`'s sake - the friction that
  motivated the original relay proposal is accepted, not resolved.
- `docs/decisions/drafts/controller-bao-via-security-ssh-relay-not-local-install.md`
  is deleted rather than promoted as originally planned - its
  Decision doesn't hold once `security` having a repo checkout turned
  out to be false. This record replaces it.
