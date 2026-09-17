---
id: DRAFT-controller-bao-via-security-ssh-relay-not-local-install
title: "bao_session.py relays to security over ssh -t, not a locally-installed bao on controller"
type: draft-adr
status: draft
---

# bao_session.py relays to `security` over `ssh -t`, not a locally-installed `bao` on `controller`

**Status:** Draft — leaning design reached, not yet spiked

## Context

Today (Stage 4 of
[`openbao-cli-standardization.md`](../../projects/openbao-cli-standardization.md),
per
[`openbao-native-cli-not-docker-based-access.md`](openbao-native-cli-not-docker-based-access.md)'s
already-`Decided`/built Decision), `controller` gets its own
personally-installed native `bao` binary, and `bao_session.py`
auto-detects whether it's running on `security` or `controller` to
decide how to fetch step-ca's root cert (a local `docker exec
step-ca` vs. `utils.repo.fetch_root_cert()`'s SSH path). This is what's
actually built and stays as-is unless and until this draft is decided
and implemented.

The friction this draft is about: `controller`'s `bao` is a second
binary with its own version pin, checked only two ways - README's
install step (now deriving from `ansible/roles/openbao_cli`'s pin
directly, so the *instructions* can't drift) and `bao_session.py`'s
own `warn_on_version_mismatch()` at login time, which only fires if
the operator actually runs `bao_session.py` rather than calling `bao`
directly. Neither is a re-check on every run the way `security`'s copy
gets one on every `deploy.yaml` (`ansible/roles/openbao_cli`'s own
before/after version comparison). `security` already has everything
`bao_session.py` needs: a version-matched native `bao` (Stage 2,
Ansible-managed) and working real-TLS trust via `step_ca_client`'s
already-local root cert. If `bao` always runs *on* `security`,
`controller` needs neither its own binary nor its own trust story -
the entire local-vs-SSH root-cert branch in `bao_session.py` exists
only because `controller` currently runs `bao` itself.

**SSH transport for the relay itself:** this project's existing
convention (per
[ADR 0030](../0030-openbao-hvac-paramiko-clients.md) and this draft's
own already-built Decision) is `paramiko`, not the `ssh` CLI via
`subprocess`, for every SSH hop so far - but every one of those hops
runs one fixed, non-interactive command and reads its output
(`fetch_root_cert`, `init_unseal.py`'s two subcommands). A `bao`
session is a different kind of problem: arbitrary interactive
commands, Ctrl-C, tab completion, terminal resize - a full generic
interactive shell, not one known prompt. `init_unseal.py`'s PTY
handling only had to drive one specific masked prompt
(`get_pty=True` plus a byte-level drain loop); reimplementing general
terminal semantics on top of a raw `paramiko` channel is exactly the
kind of hand-rolled protocol work ADR 0030 replaced in the other
direction, not something worth redoing here. The real `ssh` binary
already solves this correctly. Leaning toward exec'ing it directly
(`ssh -t <security target> ...`, inheriting this process's own stdio)
rather than extending `paramiko` to do the same job - a departure from
0030's stated preference, though 0030 only ever evaluated fixed
non-interactive commands, so a true interactive shell arguably wasn't
in its scope to begin with. Noted here explicitly so it isn't
independently re-flagged as an inconsistency later.

**Raised, deliberately not resolved here:** whether the SSH key
`bao_session.py` uses (today, the same key `security_ssh_target()`
already reads out of Ansible inventory - the operator's own admin key,
already used for full deploys and arbitrary `docker exec`) should be
restricted to only ever invoke `bao`, via an `authorized_keys`
`command=` forced command. A real restriction needs a *second,
dedicated* keypair (this key is already unrestricted for everything
else this repo does, so forcing it would break those other uses) and
a real restricted-shell wrapper on the `security` end (parse and
validate the incoming command before exec'ing `bao`, closing off shell
metacharacters and `bao`'s own `-config`/plugin-loading surface) -
itself a nontrivial, security-sensitive piece of code, not a one-line
`authorized_keys` change. Whether that restriction is worth building
at all, given the key already has much broader access to `security`
for everything else, is a separate open question this draft doesn't
take a position on.

## Decision

- `bao_session.py` drops controller-local `bao` entirely, along with
  the local-vs-SSH root-cert auto-detection (`_local_root_cert`,
  `get_root_cert`, `--controller`) that exists only to support it.
- Running on `security` itself: unchanged from today - login and spawn
  the interactive child shell locally, exactly as now.
- Running from `controller`: instead of doing any of that locally,
  exec the real `ssh` binary with a pty (`ssh -t <security target>
  ...`) to run the same login-and-session flow on `security`, using
  `security_ssh_target()`'s existing user/host/key resolution -
  `controller` never dials OpenBao's API directly and never needs
  `BAO_CACERT`/`BAO_TLS_SERVER_NAME` itself.
- `README.md`'s controller-side native-`bao` install step is removed
  once this ships - nothing left on `controller` to install or keep
  version-pinned.
- The SSH-key-restriction question (Context, above) is out of scope
  for this decision either way; the key's access stays exactly as
  broad as it is today unless a later, separate decision changes it.

## Assumptions

- **Claim:** exec'ing the real `ssh` client with `-t` and inheriting
  this process's stdio gives a fully working interactive session from
  `controller` - arbitrary `bao` subcommands, Ctrl-C forwarded
  correctly, terminal resize propagated, exit code passed through -
  indistinguishable from the operator SSHing into `security` directly.
  **Breaks if wrong:** the relayed session degrades below what
  `bao_session.py` already provides running locally on `security`
  today (per this draft's own already-built Decision), making the
  relay a downgrade rather than a simplification.
  **How checked:** a real spike from an actual `controller` machine -
  drive a real session, resize the terminal mid-session, Ctrl-C
  mid-command, confirm the exit code and revoke-on-exit both still
  work over the SSH hop specifically (session-local behavior is
  already proven; only the added hop is unverified).
- **Claim:** revoke-on-exit (today's `try`/`finally` plus explicit
  `KeyboardInterrupt` catch, confirmed live for the security-local
  case) still fires correctly when the child process is `ssh -t`
  itself rather than a local shell - including on an *unclean*
  disconnect (network blip, `security` reboot mid-session), not just a
  normal remote-shell exit.
  **Breaks if wrong:** a token could outlive the session it was
  supposed to be scoped to, quietly reintroducing the
  open-ended-`export` risk this whole project exists to close.
  **How checked:** same spike as above, plus a deliberate mid-session
  network interruption.

## Consequences

- `controller` sheds an install step and a version pin entirely - no
  more `README.md` setup bullet, no second `bao` binary to ever drift
  from `security`'s.
- `bao_session.py` gets simpler, not more complex: the local-vs-SSH
  branching disappears, leaving one code path per host instead of one
  script trying to behave like two.
- A new soft dependency: the real `ssh` client binary must be on
  `controller`'s `PATH` - already implied today (this repo already
  assumes `controller` can SSH out for deploys), so not a new
  requirement in practice, just newly load-bearing for this one script
  too.
- Departure from ADR 0030's paramiko-not-the-CLI preference for this
  one interactive case - accepted and noted explicitly (Context) so a
  future reader doesn't flag it as unexplained drift.
- The SSH-key-restriction question stays open and unresolved by this
  decision either way (Context) - today's key scope carries forward
  unchanged unless addressed separately later.
- Every doc showing a `bao_session.py` invocation from `controller`
  would need its example simplified once this ships (no more
  `--controller` flag) - folded into Stage 7's already-planned
  invocation-example pass, not a new doc effort.
