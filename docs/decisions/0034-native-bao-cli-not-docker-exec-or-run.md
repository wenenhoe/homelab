---
id: ADR-0034
title: "Native bao CLI on security/controller, not docker exec or a throwaway docker run"
type: adr
status: accepted
---

# 0034. Native bao CLI on security/controller, not docker exec or a throwaway docker run

**Status:** Accepted

Revises one specific passage of already-accepted
[ADR 0019](0019-openbao-snapshot-push-standalone.md) - not its
structural decision (`snapshot-push.sh` pushing directly to R2/B2,
never through `backup_agent`/`cloud_sync`, stands unchanged) - just
its claim that the push happens "directly from `security`" and that
the write leaf is "minted and cached only on `security`." Both were
true when 0019 was written. The Decision below moves the whole
script - login, snapshot save, encrypt, push - onto `controller`
instead, reading the same dedicated snapshot-write-scoped leaf via
`controller`'s own already-broad AppRole grant
([ADR 0020](0020-controller-single-broad-approle-not-split-by-consumer.md))
rather than a `security`-only path - confirmed to need no new Vault
policy grant, since that grant already covered this exact path.

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
  [ADR 0022](0022-controller-vault-tls-trust-via-per-run-fetched-root-cert.md)
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

A later check of `openbao_backup/snapshot-push.sh.j2`'s own
constraints found the same class of dependency `security` itself had:
it only needs `docker exec`/`docker cp` today because `bao operator
raft snapshot save <path>` runs *inside* the container. Confirmed
live: this command is a plain client-side download over the HTTPS
API - it writes the snapshot directly to wherever the *calling
process* runs, never a server-side file, confirmed by running it from
a directory with no relationship to the server's own storage path and
finding nothing written server-side. Nothing about it actually
requires `security`-local execution once a native `bao` with real
network access exists - that constraint was only ever a side effect of
routing it through `docker exec`.

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
- **The SSH hop** anywhere one is needed (root-cert fetch, or driving
  `docker exec` for init/unseal orchestration) uses `paramiko`
  directly, matching
  [ADR 0030](0030-openbao-hvac-paramiko-clients.md)'s clients -
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
  documentation alone**: `bao_session.py` (below) compares local
  `bao version` against the running server's own reported `Version`
  (already exposed free by `bao status`/`sys/health`) at login time
  and warns on mismatch, rather than resting purely on the operator
  remembering to keep the pin current.
- **One merged login+session script, not three separate ones.**
  `docker/openbao/scripts/bao-login.sh`, `bao-login-from-controller.sh`,
  and `bao-from-controller.sh` are replaced entirely by a single script
  (`tools/openbao_utils/bao_session.py`) usable from either `security`
  or `controller`. It authenticates via this module's existing
  `vault_login()` (`hvac`) rather than shelling out to `bao write
  auth/approle/login`: `secret_id` is read with Python's `getpass`
  straight into memory and passed as a function argument to `hvac` -
  never a file on disk, never a subprocess argument - a strictly
  stronger guarantee than the shell scripts' temp-file dance ever gave,
  and it removes that dance entirely. ADR 0030's hvac/paramiko
  boundary still holds: `hvac` is used for the one thing it's already
  used for elsewhere (the AppRole exchange itself), not to reimplement
  `bao`'s CLI surface - see the next bullet for why that surface still
  needs a real `bao` binary.
- **The login script hands off to a real interactive shell, not to
  hvac calls.** Once authenticated, it spawns a genuine interactive
  child shell (inheriting the terminal) with `BAO_ADDR`/`BAO_CACERT`/
  `BAO_TLS_SERVER_NAME`/`BAO_TOKEN` exported for that child process
  only - so any native `bao` subcommand (`kv get`, `operator raft
  snapshot save`, anything) keeps working completely unmodified inside
  it, rather than needing each one reimplemented against `hvac`. On
  that child exiting - normally, or via Ctrl-C - the wrapper revokes
  the token and exits. Confirmed live: a `try/finally` around the
  child reliably still runs on `SIGINT` even though Ctrl-C delivers to
  both processes at once (the child's own `sleep` was genuinely
  killed, and the parent's `finally` still printed) - but the resulting
  `KeyboardInterrupt` in the parent must also be caught explicitly, or
  a traceback prints to the operator's terminal right after cleanup
  completes.
- **No `--controller` vs. `--security` split at the interface level.**
  The script auto-detects which root-cert path to use: it tries a
  local `docker exec step-ca ...` first (only ever succeeds where a
  real `step-ca` container is directly reachable, i.e. on `security`
  itself) and falls back to the SSH-fetch-over-`paramiko` path (ADR
  0022's mechanism) otherwise. An explicit `--controller` flag exists
  purely as an override for whenever auto-detection guesses wrong, not
  as the primary interface.
- **Session-scoped token handling, not a persistent export - the
  merged login script above is the concrete shape for interactive
  access.** Login wraps a bounded interactive session (the spawned
  child shell) with a forced revoke+unset once it ends, rather than a
  bare `export` the operator has to remember to undo.
- **`snapshot-push.sh.j2` moves entirely to `controller`, native `bao`
  over the network - no `security` hop, no manual token copy-paste.**
  Since `bao operator raft snapshot save` is a client-side download
  (see Context), the whole script - login, snapshot save, GPG-encrypt,
  push to R2/B2 - now runs as one process on `controller`, replacing
  the current mint-on-`controller`/paste-on-`security` manual handoff.
  It stays a **shell script**, consistent with this file's own earlier
  resolution (native CLI, not `hvac`/Python): it does its own login
  using the native `bao` CLI directly - the same hidden-prompt,
  `-field=token` pattern `bao-login.sh` already established, just run
  locally on `controller` instead of via `docker exec` - and its own
  forced revoke via a shell `trap`, not the Python `try/finally`
  `bao_session.py` uses. Two wrapper shapes now exist in this project,
  each fitted to what it wraps: `bao_session.py` (Python, `hvac` for
  the login exchange only) for interactive multi-command access, and a
  plain shell login-run-revoke `trap` for fixed, unattended one-shot
  scripts like this one. It's rehoused at
  `tools/openbao_utils/scripts/snapshot-push.sh` - not loose in
  `tools/openbao_utils/`'s own root alongside its `.py` modules,
  matching the precedent `tools/cloud_credentials/systemd/` already
  sets for non-Python artifacts living inside a Python package
  directory, in their own named subdirectory rather than mixed in.
  **`rclone.conf`**: rendered as a `mktemp`-created, `chmod 600` temp
  file at run time rather than an Ansible-deployed conffile - the
  script reads each of the four R2/B2 credential values it needs via
  `bao kv get -mount=secret -field=value cloud_credentials/leaf/<name>`
  (using the same token it just minted), not `hvac`, keeping this file
  entirely shell. `controller`'s own policy
  (`docker/openbao/policies/controller.hcl`) already grants
  `read` on `secret/data/cloud_credentials/leaf/*` - the exact path
  these four values already live under (`secrets_registry.yaml`'s
  `vault_scope: cloud_credentials/leaf` for all four) - and that file
  already carries a comment anticipating exactly this ("So
  snapshot-push.sh can eventually authenticate as this role instead of
  the operator exporting the root token by hand"). No new Vault policy
  grant needed. The temp file is deleted in the same `trap` that
  revokes the token.
  **The GPG public key**: no new mechanism needed at all -
  `ansible/files/backup-gpg-public-key.asc` is a plain repo file (the
  current `.j2` template's `lookup('file', ...)` just reads it off
  disk, it isn't secret material), and `controller` already has the
  full repo checked out - the rewritten script references it at its
  already-known repo-relative path directly.

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
- Three separate shell scripts become one Python script in
  `tools/openbao_utils/` - a real rewrite, not a mechanical swap, in
  exchange for removing the `secret_id` temp-file dance entirely (it's
  now an in-memory `getpass` value, never written to disk at all) and
  collapsing the security/controller distinction into one code path
  instead of two diverging ones.
- `snapshot-push.sh.j2` gains its own login/revoke/credential-read logic
  instead of being handed an already-minted token and an
  Ansible-deployed `rclone.conf` - more script, but it removes the
  `docker exec`/`docker cp`/cleanup-`rm` sequence entirely (one `bao
  operator raft snapshot save <path>` call replaces all three), the
  manual SSH-and-paste step between `controller` and `security`
  disappears completely, and `rclone.conf` stops being an
  Ansible-rendered conffile at all - no new Vault policy grant needed,
  `controller`'s existing one already covers it.
- **`ansible/roles/openbao_backup/` becomes entirely unnecessary and
  should be deleted, not left unused.** Every one of its tasks -
  rendering `rclone.conf`, the GPG public key, `snapshot-push.sh`
  itself, and the `staging`/deploy directories - existed only to get
  those artifacts onto `security`. With the script, its config, and
  its working directory all moving to `controller` (a `mktemp -d`
  scratch dir, matching `bao-login-from-controller.sh`'s own pattern,
  not a persistent Ansible-managed one), nothing in this role has a
  job left. Whichever stage builds this needs to remove the role
  (tasks, templates, its Molecule scenario) and update `ansible.md`'s
  role table and `deploy.yaml`'s play list accordingly, not just stop
  calling it.
- **`docker/openbao/scripts/` also ends up empty and should go too.**
  Its only three occupants (`bao-login.sh`, `bao-login-from-controller.sh`,
  `bao-from-controller.sh`) all merge into `bao_session.py`;
  `snapshot-push.sh.j2` never lived there. Nothing else in this
  directory survives either change, so it's a second directory this
  project empties out and should remove, not two separate surprises
  found at different times.
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
