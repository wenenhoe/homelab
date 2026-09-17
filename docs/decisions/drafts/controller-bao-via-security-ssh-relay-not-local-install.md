---
id: DRAFT-controller-bao-via-security-ssh-relay-not-local-install
title: "bao_session.py relays to security over ssh -t, not a locally-installed bao on controller"
type: draft-adr
status: decided
---

# bao_session.py relays to `security` over `ssh -t`, not a locally-installed `bao` on `controller`

**Status:** Decided

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

**Spike findings, confirmed live from a real `controller` machine:**
a throwaway `ssh -t <security target> python3 <script>` relay, driving
a real interactive `bash` child exactly as `bao_session.py` would,
forwards a foreground Ctrl-C correctly (kills only the foreground job,
same as a direct SSH session - it does not tear down the whole
relayed session) and propagates `SIGWINCH` on terminal resize (`stty
size` reflected a mid-session resize immediately). A clean `exit`
passed the real exit code back to `controller` and ran the relayed
process's `finally` block. All three confirm the relay is
indistinguishable from a direct session for the cases Assumption 1 was
about.

The unclean-disconnect case (Assumption 2) does not hold as originally
assumed, and this is the one substantive change from the leaning
design above: killing the local `ssh -t` process (`kill -9`) tears
down the remote process too, but writing proof of execution to a file
on `security` (rather than the now-dead pty) showed only `SESSION
START`, never the `finally` block's cleanup line. The reason is
`SIGHUP`: `sshd` sends it to the whole remote process group once the
connection drops, and Python's default disposition for `SIGHUP` is
immediate termination - it does not unwind the stack, so a bare
`try`/`finally` never runs. This reproduced on the *easy* case (a
clean TCP FIN from a killed local client); an actual network
partition, where `security` gets no signal from the far end at all
until a keepalive/read times out, would leave the remote process alive
even longer with the token still unrevoked. The Decision below adds an
explicit `SIGHUP` handler to close this.

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
- The relayed process on `security` installs an explicit `SIGHUP`
  handler before spawning the child shell, alongside the existing
  `try`/`finally`/`KeyboardInterrupt` handling: on `SIGHUP` it runs the
  same revoke-and-cleanup path, then exits, instead of relying on
  Python's default disposition (immediate termination, bypassing
  `finally`) - confirmed live (Context, above) to be the actual
  behavior on an unclean disconnect. Without this, the relay would
  ship strictly worse than today's security-local case for exactly the
  failure mode this project exists to close.

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
- This spike's `SIGHUP` finding (Context, above) isn't specific to the
  relay: today's already-shipped security-local case (Stage 4) uses
  the same bare `try`/`finally` and would lose a token the identical
  way if the operator's own direct terminal session to `security`
  drops uncleanly - a pre-existing gap this draft surfaced but doesn't
  fix, since it's outside what this decision is about. Worth a
  follow-up item once this ships (see the project doc's Open items).
