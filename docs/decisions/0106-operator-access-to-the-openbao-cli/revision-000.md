---
id: ADR-0106
revision: 0
type: adr
title: Operator access to the OpenBao CLI
short: Operator bao CLI access
solution: A native bao binary on security and controller, with the interactive session script running on controller only
summary: How operators reach the bao CLI, replacing four overlapping docker-exec and alias patterns, and where the interactive session runs.
topic: repository-tooling
status: accepted
narrows: ADR-0111
related: [ADR-0020, ADR-0022, ADR-0104, ADR-0105]
former_ids: [ADR-0033, ADR-0034]
---

# 0106. Operator access to the OpenBao CLI

Narrows [ADR 0111 (Secrets store recovery)](../0111-recovering-the-secrets-store-from-total-loss/revision-000.md)
on one point: the snapshot push no longer runs "directly from `security`". The
whole script (login, snapshot save, encrypt, push) runs on `controller`, reading
the same snapshot-write leaf through `controller`'s existing AppRole grant
([ADR 0020 (Automation identity scope)](../0020-automation-identity-and-access-scope/revision-000.md)),
which needs no new Vault policy. Pushing directly to R2 and B2, never through
`backup_agent` or `cloud_sync`, is unchanged.

## Problem

Operators reached the `bao` CLI four ways, none documented as more correct: an
alias for `docker exec` with `BAO_SKIP_VERIFY=true` on `security`; raw `docker
exec -it openbao bao operator init` and `unseal`; scripted `docker exec` login on
`security`; and a login on `controller` that ran a throwaway container just to
borrow a binary, with real TLS verification against a root certificate fetched
over SSH ([ADR 0022 (Controller TLS trust)](../0022-controller-trust-in-the-secrets-store-tls/revision-000.md)).
Skipping verification had been accepted as loopback-only against the lab's own
CA, which justified accepting it, not keeping it: step-ca's root certificate is
local to `security`, so real verification there is nearly free.

## Context

- **`controller` is the operator's own machine**, never a `managed_hosts` member,
  so its operating system cannot be assumed. Anything installed there is a
  personal one-time step, not Ansible-automated.
- **No network path to the server exists right after a fresh init.** OpenBao's
  port is published directly, not routed through the reverse proxy, and the
  container crash-loops until `step_ca_cert` issues its leaf certificate.
  `docker exec` bypasses the network and TLS chain, which is why it works then.
- **Session tokens.** Every AppRole role (`controller`, `vault-bootstrap`,
  `r2-read-watcher`) sets a one-hour, non-renewable token. The long-lived artifact
  is `secret_id` (90 days for `controller`, never-expiring for the break-glass
  `vault-bootstrap`), never put in argv or a persisted file. Exporting
  `BAO_TOKEN` leaves it inherited by every child of that shell for as long as it
  stays exported.
- **Established on `security` against the pinned image.** The CLI package is
  `openbao_<version>_linux_amd64.deb`, and `bao version` matches the image tag.
  Its post-install starts nothing but ships an `openbao.service` unit, a
  self-signed certificate, an empty data directory and a system user, so a stray
  start would fight the container for `:8200`. The leaf certificate carries two
  DNS names and no IP name, so dialling `127.0.0.1` fails verification, which
  `-tls-server-name` fixes without depending on the name resolving. `bao operator
  unseal`'s masked prompt refuses a piped stdin, but a PTY on the paramiko channel
  works and keeps the share out of argv. `bao operator raft snapshot save` is a
  client-side download, so nothing requires `security`-local execution once a
  native `bao` has network access. `controller`'s AppRole can write and read a
  scratch entry but not delete it.
- **The interactive session script is a module in the `tools/` package**, and
  `security` has no checkout of the repository, so the claim that it runs from
  either host never held. A relay of the session to `security` over `ssh -t` was
  tried: it forwards Ctrl-C, resize and the exit code, but an unclean disconnect
  makes `sshd` send `SIGHUP`, whose default disposition ends the process without
  running its `try`/`finally`. `controller` needs a native `bao` regardless, for
  the snapshot script, so the relay bought only an extra interactive surface.
- **The Docker Python SDK's SSH transport** builds its own client from the URL,
  takes identity from `~/.ssh/config` with no hook for the key path this repo
  resolves from the inventory, and defaults to `RejectPolicy`, a different
  host-key posture from this repo's `AutoAddPolicy`.

## Decision

- **`security`**: install a native `bao` via Ansible, version-pinned to the server
  image. Immediately after install, mask the shipped `openbao.service` and remove
  the generated `/opt/openbao` and `/etc/openbao` scaffolding, so nothing can start
  a second server for `:8200`. Verify TLS against step-ca's local root certificate,
  replacing the skip-verify variable and the alias for every security-local use
  except init and unseal.
- **TLS hostname verification everywhere a native `bao` call is made**: pass
  `-tls-server-name=<app>.{{ caddy_domain }}` or `BAO_TLS_SERVER_NAME` explicitly,
  whether the call dials an address or a name.
- **`controller`**: a personally installed native `bao`, kept for the snapshot
  script whatever the session script does, documented as a one-time manual step.
- **SSH hops** (root-certificate fetch, or driving `docker exec` for init and
  unseal) use `paramiko` directly, as
  [ADR 0104 (Python client libraries)](../0104-which-client-library-each-external-service-uses/revision-000.md)
  decides, not the Docker SDK's transport.
- **Init and unseal stay security-local and `docker exec`-based**, permanently and
  by necessity (the crash-loop before certificate issuance), documented as the one
  deliberate exception. Unseal drives `docker exec ... bao operator unseal` over a
  paramiko channel with `get_pty=True`, each share entered at the masked prompt and
  never as an argument.
- **One login and session script**, `tools/openbao_utils/shell.py` (first named
  `bao_session.py` (renamed: `shell.py`)), replaces `bao-login.sh` (removed; replaced by: `shell.py`),
  `bao-login-from-controller.sh` (removed; replaced by: `shell.py`) and
  `bao-from-controller.sh` (removed; replaced by: `shell.py`). **It runs on `controller` only.** The local-versus-SSH
  detection and the `--controller` option are removed, and the SSH fetch of the
  root certificate is unconditional. Every document that said it ran from either
  host says `controller`.
- **The script authenticates through `vault_login()` (`hvac`)**, with `secret_id`
  read by `getpass` into memory, never a file or a subprocess argument. `hvac` is
  used only for the AppRole exchange, not to reimplement `bao`'s CLI.
- **It hands off to a real interactive child shell** with `BAO_ADDR`,
  `BAO_CACERT`, `BAO_TLS_SERVER_NAME` and `BAO_TOKEN` exported for that child only,
  so any native `bao` subcommand works. When the child exits, normally or by
  Ctrl-C, the wrapper revokes the token. The parent catches `KeyboardInterrupt`
  explicitly so no traceback prints after cleanup. An explicit `SIGHUP` handler
  runs the same revoke-and-cleanup path and exits, and the cleanup is idempotent
  so the handler and the ordinary `finally` can both reach it without a second
  revoke attempt. Login wraps a bounded interactive session with a forced revoke,
  not a bare `export`.
- **A version check, not documentation alone**: the script compares the local `bao
  version` with the server's reported version at login and warns on mismatch.
- **`snapshot-push.sh` moves entirely to `controller`**, using the native `bao` over
  the network with no `security` hop and no manual token copy. It stays a shell
  script doing its own login (hidden prompt, `-field=token`) and a forced revoke in
  a `trap`. Two wrapper shapes now exist, each fitted to its job: the session script
  for interactive access and a login-run-revoke `trap` for fixed, unattended
  scripts. It lives at `tools/openbao_utils/scripts/snapshot-push.sh`.
  - `rclone.conf` is a `mktemp`, mode 600 file rendered at run time, not an
    Ansible-deployed file. The script reads the four R2 and B2 credential values
    with `bao kv get -mount=secret -field=value cloud_credentials/leaf/<name>`
    using the token it just minted, and deletes the file in the same `trap` that
    revokes the token. `controller.hcl` already grants read on that path.
  - The GPG public key is the plain repo file `ansible/files/backup-gpg-public-key.asc`.

## Alternatives considered

- **Relay the interactive session to `security` over `ssh -t`.** Rejected: the
  session module is not on `security`, `controller` keeps its native `bao`
  regardless, and the relay adds an interactive surface that the `SIGHUP` gap
  showed hard to keep correct.
- **The Docker Python SDK's SSH transport for the `docker exec` half.** Not
  adopted; recorded so it is not proposed again without its reasoning.
- **Keep skipping TLS verification on `security`.** Accepted once as loopback-only,
  not kept, since real verification there costs almost nothing.

## Consequences

- One more package on `security`, with a mask-and-remove task in Ansible.
- `controller`'s setup docs grow by one manual step, and `controller` carries a
  version-pinned `bao` indefinitely.
- Every native `bao` call carries the server name, in exchange for not depending
  on an IP name the certificate cannot have.
- Three shell scripts become one Python script, which removes the `secret_id`
  temporary-file handling and the host split.
- `snapshot-push.sh` gains its own login, revoke and credential-read logic, and in
  return a single `bao operator raft snapshot save` replaces the `docker exec`,
  `docker cp` and cleanup sequence.
- `ansible/roles/openbao_backup/` has no job left and is deleted with its
  Molecule scenario; the role table and the play list are updated.
- Init and unseal instructions stay `docker exec`-based, now documented as
  load-bearing.

## Reconsideration triggers

- `security` gains a checkout of the repository, or `controller` stops needing a
  native `bao`.
- The leaf certificate gains an IP name.
