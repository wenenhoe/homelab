# 0025. Controller trusts OpenBao's TLS cert via a per-run-fetched root cert, not a committed copy or skip-verify

**Status:** Accepted

## Context

Every existing `BAO_SKIP_VERIFY=true` use in this repo
(`openbao-auth.md`'s runbook, `snapshot-push.sh.j2`) is documented as
loopback-only, against the container's own self-signed-from-our-CA
cert — "there's no real trust decision being loosened here" per
[`openbao.md`](../openbao.md)'s healthcheck section. Track A stage 4's
`ensure_secret.yaml` breaks that precedent: its Vault calls run
`delegate_to: localhost` (the operator's own machine, not `security`),
over the real LAN, to `https://openbao.{{ caddy_domain }}:8200`. Reusing
skip-verify here would be a genuine, new trust decision, not a
continuation of the documented loopback exception.

Managed hosts already solve the equivalent problem via `step_ca_client`
(`ansible/roles/step_ca_client/`): read step-ca's `root_ca.crt` fresh
from the running container each time it's needed, cache it at a
well-known host path, never committed. Nothing gives the controller —
the operator's laptop, not a managed host — an equivalent today.

Two real alternatives:

- **Commit the root cert to the repo**, like
  `ansible/files/backup-gpg-public-key.asc` (a public key, safe to
  commit). Simpler — no delegation logic in Play 0 — but it's a
  manually-maintained copy nothing re-checks against the live CA. If
  step-ca's root is ever regenerated, this goes stale silently until a
  TLS call fails with no obvious cause pointing back at this file.
- **Fetch fresh every run**, mirroring `step_ca_client`'s own pattern.
  Self-healing on CA rotation, consistent with a pattern this repo
  already trusts, at the cost of one delegated task per `deploy.yaml`
  run.

## Decision

Fetch fresh every run. Play 0 (`bootstrap-secrets.yaml`), after
`main-domain` resolves from the file cache (permanently exempt from
Vault per this stage's own scoping — see [`secrets.md`](../secrets.md)),
adds one task delegated to `security`:
`community.docker.docker_container_exec` reading `step-ca`'s
`root_ca.crt` (the same command `step_ca_client` already runs), written
to a fresh path from `ansible.builtin.tempfile` — never a fixed
filename. A fixed name in a shared temp directory is guessable, and
a process could pre-plant its own content at that path before this
task runs, which the fetch would then silently trust. `tempfile`'s
randomly-named, per-run file has nothing to pre-plant. That path is
used as `ca_path` for every `ansible.builtin.uri` call this role makes
to Vault for the rest of the run, then removed once Play 0 finishes —
never committed, never outliving the run that fetched it.

## Consequences

- One additional SSH round-trip to `security` per `deploy.yaml`/
  `maintenance.yaml`/`cleanup.yaml` invocation (anything that imports
  `bootstrap-secrets.yaml`) — the same cost `step_ca_client` already
  pays on every managed-host play that needs the root cert, just from
  one more caller.
- The temp file exists, world-unreadable-by-default per `tempfile`'s
  own mode handling, on the controller's local disk for the duration of
  one playbook run. Accepted residual exposure, same tier as every
  other credential that already touches this machine during a run
  (the SSH private key, the root token during `openbao.md`'s Init
  runbook) — not new exposure this decision introduces.
- This pattern (delegate to a real host, `docker_container_exec`,
  `tempfile`-backed, never committed) is the one to reuse for any
  future controller-side or CD-agent-side TLS client talking to an
  internal service — noted here since `cd_agent` (Track B) will need
  the same trust for its own Vault AppRole logins once it exists.
- Confirmed live: a `delegate_to: security` task needs its own explicit
  `connection: ssh` whenever the enclosing play sets `connection: local`
  at the play level (as `bootstrap-secrets.yaml`'s own play does, since
  most of its tasks genuinely delegate to `localhost`) — otherwise
  Ansible silently defaults the connection to `local` instead of
  `security`'s own SSH, and the fetch runs against the wrong machine
  entirely. Anyone reusing this pattern needs the same explicit override
  if their own enclosing play has the same shape — see
  `vault_login.yaml`'s own task comment for the full mechanism.
