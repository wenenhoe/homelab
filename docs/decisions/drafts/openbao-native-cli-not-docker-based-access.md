---
id: DRAFT-openbao-native-cli-not-docker-based-access
title: "Native bao CLI on security/controller, not docker exec or a throwaway docker run"
type: draft-adr
status: draft
---

# Native bao CLI on security/controller, not docker exec or a throwaway docker run

**Status:** Draft

## Context

Four overlapping patterns currently reach OpenBao's CLI, none of them
documented as more correct than the others:

- An interactive alias, run on `security`:
  `alias bao='docker exec -i -e BAO_TOKEN -e BAO_SKIP_VERIFY=true
  openbao bao'` (`openbao-auth.md`, `openbao-reinit-runbook.md` x3,
  `openbao-vault-bootstrap.md`).
- Raw `docker exec -it openbao bao operator init/unseal`, also on
  `security` (`openbao-reinit-runbook.md`, `openbao.md`).
- `bao-login.sh`, scp'd to and run on `security` - the same
  docker-exec-into-the-live-container model, scripted instead of
  aliased.
- `bao-login-from-controller.sh` + `bao-from-controller.sh`, run on
  `controller` - a different model entirely: a throwaway
  `docker run --rm --entrypoint bao openbao/openbao:2.6.2 ...`
  container just to borrow a `bao` binary, with real TLS verification
  via a root cert fetched fresh over SSH each run (the pattern
  [ADR 0022](../0022-controller-vault-tls-trust-via-per-run-fetched-root-cert.md)
  established, scoped specifically to `controller`).

ADR 0022 documents every existing `BAO_SKIP_VERIFY=true` use as
loopback-only against a self-signed-from-our-own-CA cert - "there's no
real trust decision being loosened" *given the situation as it stood*.
That reasoning justified accepting it, not that fixing it would be
undesirable. step-ca's root cert is a sibling container on `security`
itself, readable with no SSH hop - real verification there is nearly
free once this area is being touched anyway.

`controller` is explicitly documented as "the operator's own machine,
never a `managed_hosts` member" (`openbao-backup-restore.md`) - unlike
`security`, its OS can't be assumed, so anything installed there is a
personal one-time setup step (matching how `uv`/`ansible-core` already
work), never an Ansible-automated one.

`docker-compose.yaml.j2` publishes OpenBao's port directly
(`0.0.0.0:8200:8200`, not routed through Caddy), and the container
crash-loops immediately after a fresh init until `step_ca_cert` issues
its leaf certificate (a `deploy.yaml` Play 6 step). There is no
trustworthy network-reachable path to the server during that window -
`docker exec` bypasses the network/TLS chain entirely, which is why it
works when nothing else would.

Every AppRole role actually created in this repo (`controller`,
`vault-bootstrap`, `r2-read-watcher`) already sets `token_ttl=1h`,
`token_max_ttl=1h`, non-renewable. The long-lived artifact is
`secret_id` (90 days for `controller`; never-expiring by design for
the break-glass `vault-bootstrap` role), already handled carefully
(never argv, never a persisted file). `BAO_TOKEN` - the session token -
is currently just `export`ed in most docs, with no consistent
revoke/unset: `openbao-backup-restore.md` and
`openbao-vault-bootstrap.md`'s day-to-day section export it and never
revoke or unset it in that doc, unlike `beszel.md`/`openbao-auth.md`/
`openbao-reinit-runbook.md`. A token's 1h TTL bounds worst-case impact
regardless, but doesn't address the more everyday risk: every child
process spawned from a shell with `BAO_TOKEN` exported inherits it for
as long as it stays exported, independent of the token's own TTL.

Considered for the `docker exec` half specifically: routing it through
the Docker Python SDK's own SSH transport
(`docker.DockerClient(base_url="ssh://...")`) instead of a plain
`paramiko.exec_command("docker exec ...")`. Confirmed via source
(`docker.transport.sshconn`) that its default (`use_ssh_client=False`)
genuinely builds a `paramiko.SSHClient()` internally - no subprocess,
no shelling to `ssh`. But it builds that client itself from the URL,
defaulting to `~/.ssh/config` for identity resolution, with no obvious
hook to inject the key path this repo already looks up via Ansible
inventory (`_security_ssh_target()`); and it defaults to
`paramiko.RejectPolicy()` for host keys, a different (stricter) trust
posture than this repo's existing `AutoAddPolicy()` pattern, adopted
silently rather than deliberately. For a command that's 100% fixed
strings with no dynamic input to sanitize, the SDK's structured
`container.exec_run()` buys little over a plain `exec_command()` call
here.

## Decision

- **`security`**: install a native `bao` binary, version-pinned to
  match the Docker image's pinned server version exactly, via Ansible
  (a real `managed_hosts` member). Point it at real TLS verification
  using step-ca's already-local root cert, replacing
  `BAO_SKIP_VERIFY=true` and the `alias bao=...` convention for every
  security-local use except init/unseal itself.
- **`controller`**: a personally-installed native `bao` binary,
  documented as a one-time manual setup step, not Ansible-automated.
  `bao-login-from-controller.sh`/`bao-from-controller.sh` get rewritten
  to shell out to this real local binary instead of a throwaway
  `docker run`, keeping the same external interface
  (`BAO_TOKEN=$(bao-login-from-controller.sh <role_id>)`) and ADR
  0022's already-accepted SSH-fetched-root-cert mechanism unchanged -
  only how a `bao` binary gets obtained changes, not the trust model.
- **The SSH hop** anywhere one is needed (root-cert fetch, or driving
  `docker exec` for init/unseal orchestration) uses `paramiko`
  directly, matching
  [ADR 0030](../0030-openbao-hvac-paramiko-clients.md)'s clients -
  not the Docker SDK's own SSH transport, for the reasons in Context
  above.
- **Init/unseal stays security-local and docker-exec-based**,
  permanently, by necessity rather than convention - documented
  explicitly as the one deliberate exception, citing the crash-loop-
  before-cert-issuance constraint, rather than left implicit.
- **No custom interactive-CLI-session tooling.** OpenBao's CLI is
  designed around persistent-per-shell `BAO_ADDR`/`BAO_CACERT`/
  `BAO_TOKEN` env vars already; a native binary on both hosts gives
  "run several commands without re-invoking a wrapper" for free, for
  the duration of one bounded operation.
- **Session-scoped token handling, not a persistent export.** Every
  login wraps a bounded batch of commands with a forced revoke+unset
  once that batch finishes (a shell function/trap, not a "remember to"
  convention in prose) - bounding exposure to the wrapped block's
  runtime, not however long the surrounding shell session happens to
  stay open. Applied consistently, closing the gap in
  `openbao-backup-restore.md`/`openbao-vault-bootstrap.md`.

## Assumptions

- **Claim:** a downloaded OpenBao `.deb` matching the Docker image's
  exact pinned version installs cleanly on `security`'s current OS and
  produces a CLI that authenticates and reads/writes against the
  already-running Docker server over real TLS, pointed at step-ca's
  locally-read root cert.
  **Breaks if wrong:** the entire native-on-`security` half of this
  decision doesn't work, and security-local access stays docker-exec-
  based indefinitely, not just for init/unseal.
  **Checked by:** a time-boxed spike, before any doc/script rewrite -
  see the project doc's Stage 1.
- **Claim:** `bao operator unseal`'s per-share input can be driven
  through `paramiko.exec_command()` without a real PTY - either as one
  non-interactive invocation per share, or another confirmed-safe
  mechanism that keeps each share out of `ps`/shell history - the same
  discipline `bao-login.sh` already applies to `secret_id`.
  **Breaks if wrong:** the init/unseal orchestration needs a different
  shape - e.g. paramiko only for the surrounding setup, with the
  unseal step itself left as a real interactive `ssh` session, no
  scripting attempted around the prompts themselves.
  **Checked by:** a spike against `bao operator unseal`'s actual
  documented input handling, before Stage 3 writes any orchestration
  code.
- **Claim:** `controller`'s native `bao` binary doesn't need version-
  pinning enforcement beyond documentation, on the same footing as the
  already-unenforced `uv`/`ansible-core` requirements.
  **Breaks if wrong:** CLI/server version drift causes real
  compatibility problems in practice, needing some lighter-weight
  check (e.g. the rewritten scripts printing a warning on a version
  mismatch) rather than pure documentation.
  **Checked by:** Stage 4's own build-and-use; revisit if drift
  actually bites.

## Consequences

- One more package on `security` - accepted, same precedent as
  `python3-hvac` on the r2-read-watcher host.
- `controller`'s setup docs grow by one manual step - a new but small
  burden on setting up a fresh controller machine.
- Every login gets slightly more ceremony (an explicit wrap-and-revoke
  instead of a bare `export`), in exchange for bounding token exposure
  to one operation's runtime instead of an open-ended shell session.
- `openbao.md`/`openbao-reinit-runbook.md`'s init/unseal instructions
  stay docker-exec-based permanently - now documented as a deliberate,
  load-bearing exception instead of unexplained inconsistency.
- The Docker Python SDK's SSH transport was evaluated and deliberately
  not adopted - noted here so it isn't independently rediscovered and
  re-proposed without this reasoning attached.
