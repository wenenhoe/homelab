# Architecture Decision Records

A short record of *why* a specific design was chosen when the reasoning
is non-obvious, contested, or has a real alternative someone could
reasonably ask "why not X instead?" about. Not a changelog and not a
bug log — a fixed bug belongs in the doc it affects (stated as current
behavior) or in the PR/commit that fixed it, not here.

Write one when a decision:

- trades off two real options and the choice isn't obvious from the
  code alone (e.g. accepting a security gap because the alternative
  isn't available on a given platform)
- would be expensive to reverse, or someone new to the repo would
  otherwise have to reconstruct by reading old commits/PRs
- is still open (a known gap, tracked but not yet resolved)

Use [`TEMPLATE.md`](TEMPLATE.md) for new entries once a decision is
ready to record. Number sequentially; never renumber or delete a
superseded one — mark it `Superseded by 000N` instead, so old links
keep resolving. If the superseded ADR is referenced from
[`docs/nist-800-53-alignment.md`](../nist-800-53-alignment.md), review
whether the control mapping still holds and update it in the same
patch — the file doesn't move on supersession, so nothing else makes
that reference look broken; `check-doc-drift.py` fails the build until
it's addressed precisely because of that.

## Drafts

A numbered ADR here means "decided, and either built or being built" —
not "under consideration." A decision that depends on something
unverified (another stage's not-yet-built design, a tool's real
behavior, a component that doesn't exist yet) starts as a draft in
[`drafts/`](drafts/) instead: same shape as `TEMPLATE.md`, plus an
`Assumptions` section naming exactly what's unverified and how it gets
checked. Drafts are unnumbered, freely rewritten or deleted in place —
nothing else in this repo should ever cite one as settled.

**Hard gate:** production implementation must never begin on a draft
that still has an open `Assumptions` entry. While any entry is open,
the only engineering work allowed against that draft is a time-boxed,
throwaway spike aimed at resolving one specific entry — same as this
repo's general spike discipline, just scoped to a draft instead of a
numbered decision. Not every entry needs a spike — reading existing
code, or simply waiting on another stage to land, resolves plenty of
them without writing anything throwaway; the gate is about production
code specifically, not all de-risking activity.

A draft's **Status:** line tracks this directly (`status:` in
frontmatter), using the same vocabulary as a project stage
([`docs/projects/README.md#what-goes-in-one`](../projects/README.md#what-goes-in-one)):
`Draft` while the design itself is still being written, before its
open questions have settled into concrete `Assumptions` entries;
`De-risking` once at least one entry is open and is actively being
worked, by whatever means actually resolves it; `Decided` only once
every `Assumptions` entry is resolved — folded into Context as settled
fact, or the Decision revised to no longer need it — so the design is
genuinely settled and only implementation remains. None of these is a
promise of promotion; the file stays unnumbered and in `drafts/` until
promotion actually happens.

Promotion to a real ADR happens once the design has been `Decided` and
is actually implemented — not at decide-time, and never while an
Assumption is still open. At that point: assign the next sequential
number, drop the `Assumptions` section entirely (everything in it is
now either settled fact folded into Context, or moot), set
`Status: Accepted` directly, move the file from `drafts/` into this
directory, and add it to the index below.
Update every place elsewhere in the repo that links to the draft's old
path to the new one in the same patch — a link that still resolves
(the file exists, just moved) is easy to miss, since nothing fails
loudly the way a genuinely broken link does. If the draft is
referenced from
[`docs/nist-800-53-alignment.md`](../nist-800-53-alignment.md),
repointing the link isn't enough on its own — re-check the mapping
still holds now that the design is final, in the same patch.

A draft can also just be deleted — abandoned, or superseded by a
different approach before ever being built. When that happens, every
inward link to it needs resolving in the same patch: repoint it if
the topic has a new home (the decision that replaced it, a topic doc,
a project doc), or remove the reference outright if it doesn't.
`check-doc-drift.py` catches a dangling link to a deleted file, but
not a link quietly left pointing at the wrong thing — that part is on
whoever's deleting it.

## Index

| ADR | Status | Decision |
| :--- | :--- | :--- |
| [0001](0001-adopt-ansible-not-manual-deployment.md) | Accepted | Adopt Ansible as the only way any host is configured, replacing manual per-host `docker compose` over SSH. |
| [0002](0002-caddy-not-nginx-proxy-manager.md) | Accepted | Use Caddy, configured entirely via a checked-in `Caddyfile`, instead of Nginx Proxy Manager's UI/database-backed config. |
| [0003](0003-caddy-wildcard-certs-not-per-app.md) | Accepted, partially applied | Route most apps through one wildcard cert per host instead of one cert per app — flatter config, and avoids exposing individual app hostnames in public Certificate Transparency logs. `tinyauth` is still a deliberate exception. |
| [0004](0004-docker-socket-proxy-not-raw-socket.md) | Accepted | Any container needing Docker API access gets a `docker-socket-proxy` sidecar scoped to exactly the capabilities it needs, never the raw socket — replacing `diun`'s original unrestricted socket mount. |
| [0005](0005-named-volumes-not-bind-mounts.md) | Accepted | Use Docker-managed named volumes instead of bind mounts, to eliminate host/container UID permission friction and enable a generic backup agent; a Kubernetes migration was considered and rejected around the same time for lack of a real multi-machine cluster. |
| [0006](0006-backup-credential-blast-radius-threat-model.md) | Accepted | Threat model for the offsite backup: a compromised app host must never reach a cloud credential or another host's archives. Cloud credentials live only on `storage`; each app host's SeaweedFS identity is scoped to its own prefix. |
| [0007](0007-stepca-custom-entrypoint-not-docker-init-vars.md) | Accepted | Run `step ca init` by hand in a custom entrypoint instead of the official image's `DOCKER_STEPCA_INIT_*` auto-init, so the CA and provisioner passwords stay independent and claim duration is settable. |
| [0008](0008-stepca-cert-duration-720h.md) | Accepted, flagged for review | step-ca's default cert lifetime is 720h, not step-ca's own 24h — chosen before renewal automation existed; that automation now exists and the value hasn't been revisited. |
| [0009](0009-lldap-ldaps-cert-via-stepca-not-certbot.md) | Accepted | Issue lldap's LDAPS cert from the internal step-ca via host-level systemd timers, replacing the original certbot + DNS-01 + docker-socket-proxy sidecar pair. |
| [0010](0010-cloud-sync-copy-not-sync.md) | Accepted | `cloud_sync` relays to R2/B2/OCI via rclone `copy`, never `sync`, and cloud-side retention stays a provider-native, out-of-band lifecycle rule — the actual mechanism (not IAM scoping) that keeps a compromised on-prem host from touching the offsite copy. |
| [0011](0011-telegram-topics-not-direct-chat.md) | Accepted | Move alerting from a direct one-on-one bot chat to a group chat with Topics, one topic per concern, so a real failure doesn't get lost in routine notification noise. |
| [0012](0012-backup-freshness-check-per-host.md) | Accepted | Run backup-freshness checks per host instead of one centralized checker on `storage`, because a centralized checker needs cross-host `hostvars` facts that aren't populated under a partial `--limit` deploy. |
| [0013](0013-credential-caching-stage-1-before-secrets-manager.md) | Superseded by [0027](0027-openbao-not-file-cache-or-committed-secrets.md) | Cache rotation/leaf credentials to `ansible/files/secrets/` now; defer a real secrets manager to a later, separately-scoped project. |
| [0014](0014-r2-rotation-token-accepted-as-master-equivalent.md) | Accepted | Cache Cloudflare R2's admin token as the de facto rotation credential, accepting it's master-equivalent (unlike B2's/OCI's narrower rotation keys), because Cloudflare's API structurally can't mint a scoped delegate for it. |
| [0015](0015-credential-expiry-native-where-possible-self-tracked-where-not.md) | Accepted (OCI superseded by 0016) | All 6 leaf credentials and 3 rotation keys/tokens now expire after 90 days — B2/R2 natively, OCI via a self-tracked cache-file timestamp — checked by a systemd user timer on `controller`, not an Ansible role. |
| [0016](0016-oci-expiry-via-scim-not-self-tracked-cache-files.md) | Accepted | OCI leaf-key creation and expiry both move to Identity Domains SCIM, replacing the classic API entirely; the rotation credential (now a Confidential Application's OAuth2 client credentials) keeps self-tracked expiry, since it has no native expiry of its own. |
| [0017](0017-openbao-bootstrap-secret-split.md) | Accepted | Split secrets into recovery-critical (Shamir shares, one scoped read-only snapshot credential — live outside OpenBao permanently) and operational (everything else, Vault-only once it's up), so OpenBao can be bootstrapped from nothing. |
| [0018](0018-manual-shamir-unseal.md) | Accepted | Manual Shamir unseal, not cloud auto-unseal — `security`'s confirmed reboot history shows no unattended-reboot pattern, so the scenario auto-unseal defends against doesn't occur on this host. |
| [0019](0019-openbao-snapshot-push-standalone.md) | Accepted | `snapshot-push.sh` pushes directly from `security` to R2/B2, never routed through `backup_agent`/`cloud_sync` — keeps `storage` (and the write leaf it would otherwise need) entirely out of OpenBao's recovery path. |
| [0020](0020-controller-single-broad-approle-not-split-by-consumer.md) | Accepted | `controller` holds one broad AppRole covering hosts, leaf, and rotation secrets plus a read-only snapshot path, not split per secret family, since it's the only automation identity that exists today. |
| [0021](0021-vault-path-convention-hosts-all-for-global-secrets.md) | Accepted | Secrets with no single host owner (referenced from `group_vars/all/main.yaml`) live under `secret/data/hosts/all/<concern>/*`, inside 0020's already-Accepted `hosts/*` grant, instead of a new top-level Vault path. |
| [0022](0022-controller-vault-tls-trust-via-per-run-fetched-root-cert.md) | Accepted | The controller trusts OpenBao's TLS cert by fetching step-ca's root cert fresh from `security` into a `tempfile`-backed path every run, mirroring `step_ca_client`'s pattern — never skip-verify, never a committed copy. |
| [0023](0023-openbao-repoint-not-native-plugin.md) | Accepted | Repoint `tools/cloud_credentials`'s existing per-provider Python at OpenBao's KV v2 API instead of building a native lease-based secrets-engine plugin. Leaf credentials rotate every 30 days, rotation/master credentials every 90, as scheduled jobs on the CD agent — not `controller`. |
| [0024](0024-r2-admin-token-into-openbao.md) | Accepted | Move R2's admin token into OpenBao after all, scoped to one path/one AppRole with a per-read alert, now that scheduled rotation gives it a real automated consumer. Its 90-day cycle can only be auto-cached, never auto-minted — Cloudflare's API can't mint a replacement token itself. |
| [0025](0025-openbao-reinit-with-standing-vault-bootstrap-role.md) | Accepted | Re-init OpenBao now (not deferred to the eventual full cutover) with a standing narrow `vault-bootstrap` AppRole, so this repo can create new Vault policies/AppRoles - including ADR 0026's watcher - without a permanent root token. |
| [0026](0026-openbao-audit-device-and-r2-per-read-watcher.md) | Accepted | Enable a permanent, declarative (not API-driven) stdout audit device on OpenBao, and build a dedicated, least-privilege watcher for ADR 0024's R2 admin-token per-read alert, rather than the API/CLI audit-enable route or reusing controller's own AppRole. |
| [0027](0027-openbao-not-file-cache-or-committed-secrets.md) | Accepted | Adopt OpenBao as a standing secrets store, superseding 0013's file-cache-until-later approach — rejected Ansible Vault and SOPS/age too, since both are built around committing encrypted secrets to git, which the goal here was to avoid entirely. |
| [0028](0028-doc-governance-frontmatter-and-nist-alignment.md) | Accepted | Adopt YAML frontmatter (`id`/`type`/`status`, plus a few narrow extras) on every project/decision doc, a generator that regenerates the two hand-maintained README index tables from it, and a single narrative NIST SP 800-53 alignment doc — not per-doc compliance tags — for portfolio purposes. |
| [0029](0029-cloud-credentials-selective-sdk-adoption-not-blanket-swap.md) | Accepted | Move `tools/cloud_credentials`'s OCI SCIM and B2 flows onto their official SDKs (`oci.identity_domains.IdentityDomainsClient`, `b2sdk`), confirmed live for both; R2 and OCI's classic-IAM bootstrap stay on raw `requests`. |
| [0030](0030-openbao-hvac-paramiko-clients.md) | Accepted | Every internal Python client that talks to OpenBao directly (`cache.py`, `openbao_utils/bootstrap.py`, `openbao_utils/audit.py`, `r2_read_watcher.py`) uses `hvac`, and `paramiko` where an SSH hop is needed, replacing hand-rolled `requests`/`subprocess`; whether they also share an implementation is a separate, later decision. |
| [0031](0031-tools-secrets-package-split.md) | Accepted | New root-level `tools/` directory: `tools/cloud_credentials/` (B2/OCI/R2 minting, moved unchanged) and a shared OpenBao/Vault client split into `tools/openbao_utils/` (genuinely OpenBao-specific) and `tools/utils/` (generic repo-navigation/SSH helpers that had accreted there). |
| [0032](0032-consolidate-openbao-utility-scripts.md) | Accepted | `tools/openbao_client/` renamed to `tools/openbao_utils/`; `bootstrap_secrets.py`/`audit_secrets.py`/both restore scripts (merged) moved there from `ansible/`, `dump_vault_to_file_cache.py`/`diff_vault_backups.py` moved there from `cloud_credentials/`; `restore_all.py`/`molecule-test-all.sh` moved into a new `ansible/scripts/`. |

`docs/vm-provisioning.md` is this repo's other major architecture
decision (the OpenTofu/Ansible ownership boundary) — it predates this
directory and already documents itself as a design record, so it's
left where it is rather than moved. Once OpenTofu work actually lands,
new decisions from that effort belong here as regular numbered ADRs.
