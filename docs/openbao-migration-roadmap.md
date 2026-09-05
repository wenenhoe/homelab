# OpenBao + CD-Agent Migration Roadmap

**Status: planned, not yet built.** See
[`docs/decisions/`](decisions/README.md) (0017–0022) for the design
records this roadmap builds on. Nothing below is running today — this
is the build order once the first stage is greenlit.

## Stage status

Update this table at the start and end of each PR that works a stage.
`Not started` / `In progress` / `Done` / `Blocked: <reason>`.

| # | Stage | Track | Status |
| :-: | :--- | :-: | :--- |
| 1 | Deploy OpenBao | A | Done |
| 2 | Prove backup/restore loop | A | Not started |
| 3 | Auth and least-privilege policies | A | Not started |
| 4 | Migrate the secrets role | A | Not started |
| 5 | Repoint the cloud-credential package | A | Not started |
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
   Vault, pushed via the break-glass credential. An actual restore
   drill on a throwaway host. No secret's authoritative copy moves
   into Vault before this passes.
3. **Auth and least-privilege policies** — `controller`'s Era A
   AppRole ([0022](decisions/0022-approle-policy-structure-two-eras.md)):
   one broad policy, since it's the only automation identity that
   exists at this point.
4. **Migrate the secrets role** — `ensure_secret.yaml`'s `hex`/`uuid4`
   generation moves to check-then-write against Vault KV v2 (CAS, to
   avoid races); `manual` secrets bootstrap via an updated
   `bootstrap_secrets.py`. Must preserve `no_log: true` and
   generate-once-and-cache semantics, and still work before
   `ansible_host` resolves.
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
