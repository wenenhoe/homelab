---
id: ADR-0034
revision: 0
type: adr
title: Operator access to the OpenBao CLI
short: Operator bao CLI access
solution: A native bao binary on security and controller
summary: How operators reach the bao CLI, replacing four overlapping docker-exec and alias patterns.
topic: repository-tooling
status: accepted
narrows: ADR-0019
related: [ADR-0033, ADR-0022, ADR-0030]
---

# 0034. Operator access to the OpenBao CLI

Narrows [ADR 0019 (OpenBao offsite snapshot)](../0019-openbao-offsite-snapshot-path/revision-000.md)
on one point: the snapshot push no longer runs "directly from `security`". The
whole script (login, snapshot save, encrypt, push) runs on `controller`, reading
the same snapshot-write leaf through `controller`'s existing AppRole grant
([ADR 0020 (Automation identity scope)](../0020-automation-identity-and-access-scope/revision-000.md)),
which needs no new Vault policy. Pushing directly to R2/B2, never through
`backup_agent`/`cloud_sync`, is unchanged.

## Context

Operators reached the `bao` CLI four ways, none documented as more correct:
an `alias bao='docker exec -i ... openbao bao'` with `BAO_SKIP_VERIFY=true`
on `security`; raw `docker exec -it openbao bao operator init/unseal`; scripted
`docker exec` login on `security`; and a login on `controller` that ran a
throwaway `openbao/openbao` container just to borrow a binary, with real TLS
verification against a root cert fetched over SSH
([ADR 0022 (Controller TLS trust)](../0022-controller-trust-in-the-secrets-store-tls/revision-000.md)).

ADR 0022 accepted `BAO_SKIP_VERIFY=true` as loopback-only against our own CA, so
no real trust decision was loosened. That justified accepting it, not keeping it:
step-ca's root cert is local to `security`, so real verification there is nearly
free.

- **`controller` is the operator's own machine**, never a `managed_hosts`
  member, so its OS can't be assumed. Anything installed there is a personal
  one-time step, not Ansible-automated.
- **No network path to the server exists right after a fresh init.**
  OpenBao's port is published directly, not routed through Caddy, and the
  container crash-loops until `step_ca_cert` issues its leaf certificate
  (`deploy.yaml` Play 6). `docker exec` bypasses the network and TLS chain,
  which is why it works then.
- **Session tokens.** Every AppRole role (`controller`, `vault-bootstrap`,
  `r2-read-watcher`) sets `token_ttl=1h`, `token_max_ttl=1h`, non-renewable. The
  long-lived artifact is `secret_id` (90 days for `controller`; never-expiring
  for the break-glass `vault-bootstrap`), never put in argv or a persisted file.
  `BAO_TOKEN` was simply `export`ed in most docs, without a consistent revoke or
  unset. The 1h TTL bounds the worst case, but every child process of a shell
  with `BAO_TOKEN` exported inherits it for as long as it stays exported.
- **The Docker Python SDK's SSH transport** (`docker.DockerClient(base_url="ssh://...")`)
  was considered for the `docker exec` half. It builds a `paramiko.SSHClient()`
  itself from the URL (no subprocess), but takes identity from `~/.ssh/config`
  with no hook for the key path this repo resolves from Ansible inventory
  (`_security_ssh_target()`), and defaults to `paramiko.RejectPolicy()`, a
  different host-key posture from this repo's `AutoAddPolicy()`. For fixed
  command strings, `container.exec_run()` buys little over `exec_command()`.

Facts established on `security` against the pinned `2.6.2` image:

- The CLI package was renamed upstream: the release asset is
  `openbao_<version>_linux_amd64.deb`, not `bao_<version>_...` (which 404s).
  `bao version` matches the pinned image tag exactly.
- The `.deb`'s `postinst` starts nothing, but it ships an `openbao.service`
  unit, a self-signed cert under `/opt/openbao/tls`, an empty data dir and a
  system user, built for a standalone server. A stray `systemctl start openbao`
  would fight the Docker container for `:8200`.
- The leaf cert `step_ca_cert` issues carries two DNS SANs
  (`{{ step_ca_cert_common_name }}` and `{{ step_ca_cert_common_name }}.{{ caddy_domain }}`)
  and no IP SAN. Dialing `127.0.0.1` fails with `x509: cannot validate
  certificate for 127.0.0.1 because it doesn't contain any IP SANs`.
  `-tls-server-name` (or `BAO_TLS_SERVER_NAME`) fixes this while still dialing
  `-address`, with no dependency on the FQDN resolving where the CLI runs.
- `bao operator unseal`'s masked prompt refuses a non-PTY stdin pipe
  (`file descriptor 0 is not a terminal`). Allocating a PTY on the paramiko
  channel (`get_pty=True`) and feeding the share over it works, and the share
  never touches argv or `ps`; a 3-share/2-threshold throwaway instance unsealed
  this way.
- `controller`'s AppRole can write and read a scratch KV entry but cannot
  delete it, the intended least-privilege scope.
- `bao operator raft snapshot save <path>` is a client-side download over the
  HTTPS API. It writes where the *calling process* runs, never server-side, so
  nothing requires `security`-local execution once a native `bao` with network
  access exists. The `docker exec`/`docker cp` in the old
  `openbao_backup/snapshot-push.sh.j2` (removed; replaced by: `snapshot-push.sh`) was a side effect of routing through
  `docker exec`.

## Decision

- **`security`**: install a native `bao` via Ansible, version-pinned to match
  the Docker image's server version. Immediately after install, mask the
  shipped `openbao.service` and remove the auto-generated
  `/opt/openbao`/`/etc/openbao` scaffolding, so nothing can start a second
  server competing for `:8200`. Verify TLS against step-ca's local root cert,
  replacing `BAO_SKIP_VERIFY=true` and the alias for every security-local use
  except init/unseal.
- **TLS hostname verification everywhere a native `bao` call is made**: pass
  `-tls-server-name=<app>.{{ caddy_domain }}` (or `BAO_TLS_SERVER_NAME`)
  explicitly. The leaf cert has no IP SAN and never will, so any call that
  dials by IP needs it, and making it explicit means it doesn't matter whether
  a call dials an IP or a FQDN.
- **`controller`**: a personally-installed native `bao`, documented as a
  one-time manual step.
- **SSH hops** (root-cert fetch, or driving `docker exec` for init/unseal) use
  `paramiko` directly, matching
  [ADR 0030 (OpenBao Python client)](../0030-openbao-client-implementation-in-repo-python/revision-000.md),
  not the Docker SDK's transport.
- **Init/unseal stays security-local and `docker exec`-based**, permanently and
  by necessity (the crash-loop before cert issuance), documented as the one
  deliberate exception. Unseal drives `docker exec ... bao operator unseal`
  over a paramiko channel with `get_pty=True`, each share entered at the masked
  prompt, never as an argument.
- **One merged login+session script** (`tools/openbao_utils/bao_session.py`)
  replaces `bao-login.sh` (removed), `bao-login-from-controller.sh` (removed) and
  `bao-from-controller.sh` (removed), usable from `security` or `controller`. It
  authenticates through the module's existing `vault_login()` (`hvac`), with
  `secret_id` read by `getpass` into memory: never a file, never a subprocess
  argument. `hvac` is used only for the AppRole exchange, not to reimplement
  `bao`'s CLI surface.
- **The script hands off to a real interactive child shell** with
  `BAO_ADDR`/`BAO_CACERT`/`BAO_TLS_SERVER_NAME`/`BAO_TOKEN` exported for that
  child only, so any native `bao` subcommand works unmodified. When the child
  exits, normally or by Ctrl-C, the wrapper revokes the token. A `try/finally`
  around the child still runs on `SIGINT`, but the parent's `KeyboardInterrupt`
  must also be caught explicitly, or a traceback prints after cleanup.
- **No `--controller` vs `--security` split.** The script tries a local
  `docker exec step-ca ...` for the root cert first (it succeeds only on
  `security`) and falls back to the SSH fetch of ADR 0022. `--controller`
  exists only as an override when auto-detection guesses wrong.
- **Session-scoped token handling**: login wraps a bounded interactive session
  with a forced revoke, not a bare `export` the operator must undo.
- **A version check, not documentation alone**: `bao_session.py` compares local
  `bao version` with the server's reported `Version` at login and warns on
  mismatch.
- **`snapshot-push.sh` moves entirely to `controller`**, native `bao` over the
  network, with no `security` hop and no manual token copy-paste. It stays a
  shell script doing its own login with the native CLI (hidden prompt,
  `-field=token`) and a forced revoke via a shell `trap`. Two wrapper shapes
  now exist, each fitted to its job: `bao_session.py` for interactive
  multi-command access, and a plain login-run-revoke `trap` for fixed,
  unattended scripts. It lives at `tools/openbao_utils/scripts/snapshot-push.sh`,
  in its own subdirectory like `tools/cloud_credentials/systemd/`.
  - **`rclone.conf`** is a `mktemp`, `chmod 600` temp file rendered at run
    time, not an Ansible-deployed conffile. The script reads the four R2/B2
    credential values with `bao kv get -mount=secret -field=value
    cloud_credentials/leaf/<name>` using the token it just minted.
    `controller.hcl` already grants `read` on `secret/data/cloud_credentials/leaf/*`
    and anticipated this use. The temp file is deleted in the same `trap` that
    revokes the token.
  - **The GPG public key** is the plain repo file
    `ansible/files/backup-gpg-public-key.asc`, which `controller`'s checkout
    already has.

## Consequences

- One more package on `security`, same precedent as `python3-hvac` on the
  r2-read-watcher host. Every fresh install also needs the mask-and-remove step,
  so the Ansible task does it rather than documenting it.
- `controller`'s setup docs grow by one manual step.
- Every native `bao` call carries `-tls-server-name`/`BAO_TLS_SERVER_NAME`, in
  exchange for not depending on an IP SAN the cert can't have or on the dialing
  host resolving the FQDN.
- Three shell scripts become one Python script, a real rewrite, in exchange for
  removing the `secret_id` temp-file handling and the security/controller split.
- `snapshot-push.sh` gains its own login, revoke and credential-read logic. In
  return one `bao operator raft snapshot save <path>` replaces the
  `docker exec`/`docker cp`/cleanup sequence, the manual paste between
  `controller` and `security` disappears, and `rclone.conf` stops being
  Ansible-rendered.
- `ansible/roles/openbao_backup/` has no job left (its artifacts existed only to
  reach `security`) and is deleted, with its Molecule scenario, and
  `ansible.md`'s role table and `deploy.yaml`'s play list are updated.
  `docker/openbao/scripts/` is emptied by the merge and removed.
- Every login carries a little more ceremony, bounding token exposure to one
  operation instead of an open-ended shell session.
- Init/unseal instructions in `openbao.md` and `openbao-reinit-runbook.md` stay
  `docker exec`-based, now documented as load-bearing.
- The Docker SDK's SSH transport was evaluated and not adopted; recorded so it
  isn't re-proposed without this reasoning.
