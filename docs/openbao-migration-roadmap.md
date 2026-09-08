# OpenBao + CD-Agent Migration Roadmap

**Status: Track A in progress, Track B not started.** See
[`docs/decisions/`](decisions/README.md) (0017–0022) for the design
records this roadmap builds on. Stages 1–4 are built and proven live;
stage 5's storage-layer repoint is too, but the stage isn't Done until
ADR 0019's own per-read alert requirement is built — see the table
below and its Open items.

## Stage status

Update this table at the start and end of each PR that works a stage.
`Not started` / `In progress` / `Done` / `Blocked: <reason>`.

| # | Stage | Track | Status |
| :-: | :--- | :-: | :--- |
| 1 | Deploy OpenBao | A | Done |
| 2 | Prove backup/restore loop | A | Done |
| 3 | Auth and least-privilege policies | A | Done |
| 4 | Migrate the secrets role | A | Done |
| 5 | Repoint the cloud-credential package | A | Blocked: R2 per-read alert (ADR 0019) — see Open items |
| 6 | Full cutover, decommission file cache | A | Not started |
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
6. **Full cutover drill, then decommission the file cache** — wipe
   `ansible/files/secrets/` on a test controller, restore a full
   environment purely from Vault. Only after that passes: delete the
   file-based mechanism, retire `bootstrap_secrets.py`'s file-writing
   path, and update `secrets.md`/`secrets-rotation.md`/
   `cloud-credential-creation.md`/`disaster-recovery.md` to describe
   Vault as the sole source.

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
- `snapshot-push.sh` still needs a human-exported root token —
  `controller`'s Era A policy now grants the read it needs, but the
  script itself isn't wired to log in via that AppRole yet. Needs a
  spike on `bao write -f auth/approle/login ...`'s exact output shape
  first — see [`openbao-backup-restore.md`](openbao-backup-restore.md)'s
  open follow-ups.
- Root-token recovery once revoked (`openbao-auth.md`'s stage 3 step)
  has no confirmed working path: a real 2.6.2 instance returned a 403
  on `sys/generate-root-token/*` for controller's own AppRole token,
  and nothing else in this Vault holds `sudo` to grant that access
  either — confirmed live, not assumed, during Track A stage 5's own
  testing. This also means `openbao-backup-restore.md`'s restore-drill
  step 6 ("authenticate with the break-glass root token") assumes a
  credential stage 3's revocation removes; the two docs contradict
  each other and need reconciling. Not yet decided between: never
  fully revoke root (keep it in the offline break-glass bundle
  instead); grant a narrow `sudo`-on-`sys/generate-root-token/*`
  policy before revoking root, specifically to keep this path open; a
  full OpenBao re-init with a fresh break-glass bundle as part of a
  future cutover (raised, not scoped); or confirming recovery-mode
  server start as the real mechanism. Needs its own ADR once decided —
  touches `openbao-auth.md`, `openbao-backup-restore.md`, and possibly
  ADR 0022.
- `openbao-backup-restore.md` states the pinned image is `2.5.4`; the
  real, currently-running version is `2.6.2` (confirmed live, same
  session as the finding above) — that doc, and anything else assuming
  2.5.x behavior, needs a pass once the root-token question above is
  settled, since the two are related (2.6.2 is also where
  `generate-root`'s authenticated-endpoint behavior changed).
