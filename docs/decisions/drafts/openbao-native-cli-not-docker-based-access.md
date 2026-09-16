---
id: DRAFT-openbao-native-cli-not-docker-based-access
title: "Native bao CLI on security/controller, not docker exec or a throwaway docker run"
type: draft-adr
status: decided
---

# Native bao CLI on security/controller, not docker exec or a throwaway docker run

**Status:** Decided

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

Confirmed live (spike, `security`, this exact `2.6.2` pin), settling
every open question below:

- The CLI package was renamed upstream: the correct release asset is
  `openbao_2.6.2_linux_amd64.deb`, not `bao_2.6.2_linux_amd64.deb`
  (that naming 404s for this release). `dpkg -i` installs cleanly with
  one dependency (`openssl`, already present per the README), and
  `bao version` reports exactly `OpenBao v2.6.2 (dd9c19c...)` -
  an exact match to the pinned Docker image tag.
- The `.deb`'s `postinst` does **not** start anything - it only
  generates its own self-signed TLS cert under `/opt/openbao/tls`,
  creates a system user `openbao`, and runs `systemctl daemon-reload`.
  It does, however, ship a full `openbao.service` unit plus that
  self-signed cert and an empty data dir, built to run a *standalone*
  server - none of which this project wants, and left alone it's a
  live risk: a stray `systemctl start openbao` later would try to bind
  `:8200` and fight the Docker container for it.
- The leaf cert `step_ca_cert` issues for `openbao` carries exactly two
  DNS SANs (`{{ step_ca_cert_common_name }}` and
  `{{ step_ca_cert_common_name }}.{{ caddy_domain }}` -
  `ansible/roles/step_ca_cert/tasks/main.yaml`) and never an IP SAN.
  Dialing `127.0.0.1` (the obvious loopback address once
  `BAO_SKIP_VERIFY` is gone) fails hostname verification outright:
  `x509: cannot validate certificate for 127.0.0.1 because it doesn't
  contain any IP SANs` - reproduced live, not hypothetical.
  `-tls-server-name=<one of the cert's real SANs>` (equivalently
  `BAO_TLS_SERVER_NAME`) fixes this while still dialing whatever
  `-address` says - confirmed live - decoupling "what to connect to"
  from "what hostname to verify against," with no dependency on that
  FQDN actually resolving from wherever the CLI runs.
- `bao operator unseal`'s masked interactive prompt refuses a bare,
  non-PTY stdin pipe outright - confirmed live:
  `file descriptor 0 is not a terminal`, not a race or a retriable
  failure. Allocating a real PTY on the same channel
  (`paramiko`'s `get_pty=True`) and feeding the share over it, driven
  entirely programmatically, works cleanly and the share never
  touches argv or `ps` - confirmed live by fully unsealing a real
  3-share/2-threshold throwaway instance this way (one share via the
  positional argument, one via a PTY-fed prompt).
- Confirmed live on `security`: `controller`'s AppRole
  (ADR 0020) can write and read a scratch KV entry but fails to delete
  it - the intended least-privilege scope working as designed, not a
  defect.

## Decision

- **`security`**: install a native `bao` binary, version-pinned to
  match the Docker image's pinned server version exactly, via Ansible
  (a real `managed_hosts` member). Immediately after install: mask the
  shipped `openbao.service` unit and remove the auto-generated
  `/opt/openbao`/`/etc/openbao` scaffolding, so nothing on the host can
  ever start a second, standalone OpenBao server competing for `:8200`
  - the `.deb`'s installer creates this by default and this project has
  no use for it. Point the CLI at real TLS verification using
  step-ca's already-local root cert, replacing `BAO_SKIP_VERIFY=true`
  and the `alias bao=...` convention for every security-local use
  except init/unseal itself.
- **TLS hostname verification, everywhere a native `bao` call is
  made**: pass `-tls-server-name=<app>.{{ caddy_domain }}` (or the
  `BAO_TLS_SERVER_NAME` env var) explicitly, rather than relying on
  whatever hostname `-address` happens to use. The leaf cert has no IP
  SAN and never will (see Context), so any call that dials by IP -
  `security`'s own loopback calls included - needs this regardless;
  making it explicit everywhere means it doesn't matter whether a
  given call dials an IP or a FQDN, or whether that FQDN happens to
  resolve from wherever the call runs.
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
  before-cert-issuance constraint, rather than left implicit. The
  unseal step specifically drives `docker exec ... bao operator
  unseal` over a paramiko channel with `get_pty=True` (see Context) -
  each share entered through the real masked prompt, never as a
  positional argument, so it never appears in argv or `ps`.
- **Controller's native `bao` gets a lightweight version check, not
  documentation alone**: the rewritten scripts compare local
  `bao version` against the running server's own reported `Version`
  (already exposed free by `bao status`/`sys/health`) and warn on
  mismatch, rather than resting purely on the operator remembering to
  keep the pin current.
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

## Consequences

- One more package on `security` - accepted, same precedent as
  `python3-hvac` on the r2-read-watcher host. Installing it is no
  longer a one-line `dpkg -i`: it also requires masking the shipped
  `openbao.service` unit and removing its auto-generated
  `/opt/openbao`/`/etc/openbao` scaffolding immediately after, every
  time it's freshly installed - one more thing Stage 2's Ansible task
  has to do, not just document.
- `controller`'s setup docs grow by one manual step - a new but small
  burden on setting up a fresh controller machine.
- Every native `bao` invocation carries an explicit
  `-tls-server-name`/`BAO_TLS_SERVER_NAME` - one more flag than a bare
  `-address` - in exchange for never depending on the leaf cert
  gaining an IP SAN it structurally can't have, or on whichever host
  is dialing being able to resolve the FQDN itself.
- Every login gets slightly more ceremony (an explicit wrap-and-revoke
  instead of a bare `export`), in exchange for bounding token exposure
  to one operation's runtime instead of an open-ended shell session.
- The rewritten scripts carry a small local version check (comparing
  `bao version` against the server's reported `Version`) rather than
  relying on documentation alone to keep `controller`'s pin current.
- `openbao.md`/`openbao-reinit-runbook.md`'s init/unseal instructions
  stay docker-exec-based permanently - now documented as a deliberate,
  load-bearing exception instead of unexplained inconsistency.
- The Docker Python SDK's SSH transport was evaluated and deliberately
  not adopted - noted here so it isn't independently rediscovered and
  re-proposed without this reasoning attached.
