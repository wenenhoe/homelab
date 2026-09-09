# OpenBao + CD-Agent Migration Roadmap

**Status: Track A complete, Track B not started.** See
[`docs/decisions/`](decisions/README.md) (0017–0022) for the design
records this roadmap builds on. All 6 Track A stages are built and
proven live, including the full cutover drill.

## Stage status

Update this table at the start and end of each PR that works a stage.
`Not started` / `In progress` / `Done` / `Blocked: <reason>`.

| # | Stage | Track | Status |
| :-: | :--- | :-: | :--- |
| 1 | Deploy OpenBao | A | Done |
| 2 | Prove backup/restore loop | A | Done |
| 3 | Auth and least-privilege policies | A | Done |
| 4 | Migrate the secrets role | A | Done |
| 5 | Repoint the cloud-credential package | A | Done |
| 6 | Full cutover, decommission file cache | A | Done |
| 7 | CD agent build | B | Not started |

## Two tracks, run sequentially

This migration is two largely independent pieces of work: replacing
the file-based secrets cache with OpenBao, and replacing manual
`ansible-playbook` deploys with a pull-based CD agent
([0020](decisions/0020-pull-based-cd-agent-not-self-hosted-github-runner.md)).
Only their final step actually depends on the other: the CD agent's
own OpenBao AppRoles
([0022](decisions/0022-approle-policy-structure-two-eras.md)) can't be
built until OpenBao holds real credentials to scope policies against.

Rather than build both at once, they run one after the other — the
OpenBao track finishes completely, including retiring the file cache,
before the CD-agent track starts. This means the CD agent is built
directly against Vault-backed secrets from day one; there's no interim
design needed for a CD agent that still reads the old file cache.

## Track A — OpenBao

Dependency-ordered: each stage assumes the previous one is not just
built, but **proven**.

1. **Deploy OpenBao** — single-node, raft storage, on `security` (same
   trust tier as `step-ca`/`tinyauth`/`lldap`), TLS via the existing
   internal PKI. Init, unseal
   ([0021](decisions/0021-manual-shamir-unseal.md)), and immediately
   generate the offline break-glass bundle
   ([0017](decisions/0017-openbao-bootstrap-secret-split.md)).
2. **Prove the backup/restore loop** — scheduled
   `bao operator raft snapshot save`, GPG-encrypted independently of
   Vault, pushed via its own standing write-leaf credential — not the
   break-glass restore credential, which stays read-only and reserved
   for actual disaster recovery
   ([0023](decisions/0023-openbao-snapshot-push-standalone.md)). An
   actual restore drill on a throwaway host, verified against a real
   secret value round-tripped through backup and restore, not just a
   clean exit code. No secret's authoritative copy moves into Vault
   before this passes.
3. **Auth and least-privilege policies** — `controller`'s Era A
   AppRole ([0022](decisions/0022-approle-policy-structure-two-eras.md)):
   one broad policy, since it's the only automation identity that
   exists at this point. See [`openbao-auth.md`](openbao-auth.md) for
   the policy, the runbook, and the root-token revocation this stage
   ends with.
4. **Migrate the secrets role** — `ensure_secret.yaml`'s `hex`/`uuid4`
   generation moves to check-then-write against Vault KV v2 (CAS, to
   avoid races); `manual` secrets bootstrap via an updated
   `bootstrap_secrets.py`. Must preserve `no_log: true` and
   generate-once-and-cache semantics, and still work before
   `ansible_host` resolves. See
   [ADR 0024](decisions/0024-vault-path-convention-hosts-all-for-global-secrets.md)/
   [0025](decisions/0025-controller-vault-tls-trust-via-per-run-fetched-root-cert.md)
   for two design points this stage needed that weren't settled going
   in (the Vault path taxonomy for secrets with no single host owner,
   and how the controller trusts OpenBao's TLS cert over a real network
   hop — including a real `delegate_to`/connection gotcha found and
   fixed along the way, see 0025's own Consequences). Proven against a
   real OpenBao instance: a live `openbao-auth.md` runbook, a real
   `deploy.yaml`/`bootstrap_secrets.py` invocation, and all four
   Molecule scenarios (`vault_backed`, `rotate_secret`,
   `vault_approle_missing`, `vault_manual_missing`) pass, including
   `idempotence` where applicable — 97.6% task coverage, with the one
   remaining gap (a genuine concurrent CAS create-race, not
   deliberately engineerable in a single scenario) documented as a
   floor in `thresholds.yaml` rather than left silently untested — see
   `docs/ci.md`'s coverage-gate section.
5. **Repoint the cloud-credential package** —
   `ansible/cloud_credentials/` reads/writes Vault instead of files,
   preserving every provider quirk
   ([0018](decisions/0018-openbao-repoint-not-native-plugin.md)),
   including R2's admin token moving in as a scoped exception
   ([0019](decisions/0019-r2-admin-token-into-openbao.md)).
6. **Full cutover drill, then decommission the file cache** — done.
   Wiped `ansible/files/secrets/` down to the three permanent bootstrap
   exceptions (`main-domain`, `openbao-controller-role-id`/
   `-secret-id`) on a real controller, proved a full deploy — write
   leaf, read leaf, and every other secret — resolves purely from
   Vault, including live `rclone lsd` against R2/B2/OCI with the
   rendered credentials, not just a non-empty value. The file-based
   generation mechanism (hex/uuid4 file-cache branches, `bootstrap_secrets.py`'s
   cloud-credential prompting) is deleted from the code, not just
   unused — see `secrets.md`/`secrets-rotation.md`/
   `cloud-credential-creation.md` for the current, Vault-as-sole-source
   state. `disaster-recovery.md` never described the storage mechanism
   directly, so it needed no change.

## Track B — CD agent

Starts once Track A's stage 6 has passed — by this point OpenBao is
the only secrets store, so the CD agent is built against it directly,
not against the file cache.

- Pull-based CD agent per
  [0020](decisions/0020-pull-based-cd-agent-not-self-hosted-github-runner.md):
  a dedicated LAN host running systemd-timer pollers that invoke
  `preloop` against GitHub Actions-format workflow files for
  deploy/maintenance/rotation/freshness, zero inbound ports.
- Its own OpenBao AppRoles
  ([0022](decisions/0022-approle-policy-structure-two-eras.md)):
  `cd-agent-deploy` and `cd-agent-rotation`, CIDR-bound to its fixed
  LAN address, scoped separately per job.
- Once those AppRoles are live and proven, `controller`'s Era A
  AppRole is deleted outright — `controller` holds no standing Vault
  credential after this point.

## Open items carried into the build

- `preloop`'s CLI event-flag behavior beyond bare `pull_request` is
  unverified — needs a spike before Track B's deploy/rotation jobs are
  built on it
  ([0020](decisions/0020-pull-based-cd-agent-not-self-hosted-github-runner.md)).
- Which cloud credentials beyond B2/R2/OCI get rotation automation,
  and whether "rotation" means alert-only or full rotate-and-revoke,
  isn't scoped yet.
- The shared SSH private key across all managed hosts (and possibly
  the maintainer's laptop) hasn't been split into a CD-agent-only key.
- ~~`snapshot-push.sh` still needs a human-exported root token~~ —
  resolved (Track A stage 6). Verified live against a real OpenBao
  2.6.2 instance: `bao write -f auth/approle/login role_id=<x>
  secret_id=@<file>` returns the client token under `-field=token`
  cleanly, no different from the shape `bao-login-from-controller.sh`
  already assumed. No code change needed in `snapshot-push.sh`
  itself — it already just reads `BAO_TOKEN` from the environment,
  agnostic to how it was obtained. Fixed
  [`openbao-backup-restore.md`](openbao-backup-restore.md)'s "Running a
  backup" section to obtain it via `controller`'s AppRole (same
  `bao-login-from-controller.sh` flow `openbao-auth.md`'s own step 6
  uses) instead of the break-glass root token.
- `openbao-backup-restore.md` wrongly stated the pinned image was
  `2.5.4`; the real, currently-running version is `2.6.2`. Fixed the
  factual claim (Track A stage 6) — still open: the specific
  snapshot-save/restore behaviors that doc describes as "confirmed
  live" were only ever confirmed against `2.5.4`, not re-verified
  against `2.6.2`, and `2.6.2` is also where `generate-root`'s
  authenticated-endpoint behavior changed (see
  [ADR 0027](decisions/0027-openbao-reinit-with-standing-vault-bootstrap-role.md)'s
  Context) — a live spike during the next restore drill, not something
  fixable from reading code alone.
