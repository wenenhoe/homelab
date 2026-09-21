# Architecture Decision Records

A decision record explains *why* the system is built the way it is, when
the reasoning isn't obvious from the code. It is not a changelog, a bug
log, a plan, or a description of current behavior — those live in git
history, [`projects/`](../projects/README.md), and topic docs
([`docs/README.md`](../README.md)).

Write one when a decision:

- trades off two real options and the choice isn't obvious from the code
  alone (e.g. accepting a security gap because the alternative isn't
  available on a given platform)
- would be expensive to reverse, or someone new would otherwise have to
  reconstruct it from old commits
- is still open — a known gap, tracked but not yet resolved

Skip it for a trivial or cheaply reversible choice, an implementation
detail inside an established pattern, or a temporary experiment.

## Lineages and revisions

One **lineage** per problem: a directory `NNNN-problem-slug/` holding one
`revision-NNN.md` per solution tried for it: `revision-000.md` is the
original, and each later solution takes the next number. The lineage's
number identifies the problem and is never reused. The title names the problem, never the
solution ("Secret storage", not "OpenBao, not a file cache"); each
revision's `solution:` field carries the answer. Use
[`TEMPLATE.md`](TEMPLATE.md).

Before creating a lineage, check that:

1. the problem can be stated without naming a solution;
2. a different solution could later answer the same problem;
3. replacing the solution would replace the whole record. If part of it
   would still stand, that part is a second problem — make two lineages.

A lineage is not a topic grouping. Several decisions that make up one
initiative are separate lineages sharing a `topic:`; the generated index
below groups by it.

## Revision states

| State | Meaning | Reasoning may change? |
| :--- | :--- | :--- |
| `working` | A solution under consideration; open assumptions allowed. | Yes |
| `approved` | No open assumptions; production implementation may begin. | Yes, but a new material assumption returns it to `working`. |
| `accepted` | Implemented and on `main`. | No — editorial fixes only. |
| `superseded` | Replaced by a later revision that is itself `accepted`. | No |
| `abandoned` | A `working` revision no longer pursued. Keep it if the rejected reasoning is useful; delete it if it was only exploration. | No |
| `retired` | The problem no longer exists and nothing replaces the solution. | No |

```text
working ─────► approved ─────► accepted ─────► superseded
   │  ▲            │                │       (a successor is accepted)
   │  └────────────┘                └─────► retired
   │   new material assumption
   └─────► abandoned
```

`accepted` means what most ADR practice means by it — binding and
immutable. `approved` is the state before that: authorized to build, not
yet built.

- Only one revision per lineage is `accepted`. A successor can be
  `working` or `approved` at the same time; the older revision becomes
  `superseded` only once the successor is `accepted`, and the successor
  declares `supersedes:` back.
- A material change to an `accepted` or `superseded` revision is a new
  revision in the same lineage, never an edit. When a superseded ADR is
  referenced from [`nist-800-53-alignment.md`](../nist-800-53-alignment.md),
  re-check the mapping in the same patch; `check-doc-drift.py` fails
  until it is addressed.
- Two solutions worked at once for the same problem are two `working`
  revisions; one is abandoned or superseded when the other is accepted.
  Numbers record the order they were created in, not which is preferred.

## Assumptions

An **assumption** is an explicitly identified condition that must be true
for the solution to be valid. Only open ones are recorded, under
`## Assumptions`; resolving one folds the fact into Context (or changes
the Decision) and deletes the entry. A revision with any entry can't be
`approved` — `check-doc-drift.py` enforces it — and only a time-boxed,
throwaway spike, or reading code, may work on one meanwhile.

Unknown unknowns are not predicted. When implementation finds a
condition that invalidates the solution, record it as an assumption and
return the revision to `working`; the project stops (see
[`docs/projects/README.md#stop-conditions`](../projects/README.md#stop-conditions)).
An agent may do exactly that — append an open assumption and set
`approved` → `working` — and nothing else to an `approved` or `accepted`
revision.

## Editing a revision

- **Editorial** (typos, a wrong fact that was wrong at the time, a link)
  — any state.
- **Metadata** (`status`, `supersedes`, `superseded_by`, `narrows`,
  `related`, `former_ids`) — any state; it records lifecycle, not
  reasoning.
- **Material** (the solution, its rationale, its validity conditions) —
  in place while `working` or `approved`; a new revision once `accepted`.

If it is unclear which side a change falls on, treat it as material.

## Partial supersession

When a later solution replaces only part of an earlier revision's scope,
don't edit the old record. The new lineage covers just that slice and
declares `narrows: ADR-NNNN`; the index shows "Narrowed by" on the old
one. The sizing check above is what prevents this — it only happens when
an earlier record bundled two problems.

## Projects

An `approved` revision is what a [project](../projects/README.md)
implements, linked by the project's `decision:` field. The revision
becomes `accepted` in the pull request that completes the work, and the
resulting behavior is described in topic docs.

## Drafts

Unnumbered drafts under [`drafts/`](drafts/) are being converted into
`working` revisions — `revision-000` of a new lineage, or a later
revision of an existing one. Nothing new starts there. Until converted,
a draft's hard gate holds: no production work while an `Assumptions`
entry is open, and `status: decided` means every entry is resolved.
Converting or deleting a draft repoints or removes every link to it in
the same patch.

## Flat ADRs

Files `NNNN-slug.md` directly in this directory predate lineages. Each is
the original (`revision-000`) of its own lineage, `accepted` (or `superseded`), and is
re-filed into a lineage directory by a mechanical patch that changes only
frontmatter and link targets. Both layouts validate until then.

## Lineages

### Documentation & process

| ADR | Problem | Current solution | Status | Notes |
| :--- | :--- | :--- | :--- | :--- |
| [0037](0037-decision-and-project-documentation-workflow/revision-000.md) | **Recording decisions, tracking execution, and keeping docs true** — How why, what-remains, and what-is-true-now are kept apart, and how an implementer knows what is authorized and when to stop. | Problem-oriented ADR lineages with gated revisions, projects as execution records, topic docs describing main | Approved | — |

## Legacy index

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
| [0033](0033-bao-session-local-only-drops-broken-security-path.md) | Accepted | `bao_session.py` stays local to `controller` - the drafted `security`-relay never had a working "local" half to relay away from (the repo isn't checked out there), and `controller`'s native `bao` stays regardless for `snapshot-push.sh`'s sake. Adds an explicit `SIGHUP` handler for the unclean-disconnect gap the relay spike surfaced. |
| [0034](0034-native-bao-cli-not-docker-exec-or-run.md) | Accepted | Native `bao` CLI on `security` (Ansible-managed) and `controller` (personal setup), real TLS via `-tls-server-name`, replacing the `docker exec`/alias/throwaway-`docker run` patterns everywhere except init/unseal (stays `docker exec`, permanently, by necessity). Merges the three retired `bao-*.sh` scripts into `bao_session.py`; moves `snapshot-push.sh` onto `controller` entirely - revises [0019](0019-openbao-snapshot-push-standalone.md)'s now-stale "from `security`" detail. |
| [0035](0035-not-adopting-kubernetes-on-current-hardware.md) | Accepted | Stay on Docker Compose + Ansible on the single Proxmox host; Kubernetes doesn't pay for itself given per-node overhead on a 6-core/32GB box, and an OCI free-tier instance can't safely sit in a control-plane's consensus quorum regardless. Revisit only on a real trigger (workload variance, expanded hardware, a genuine rolling-deploy need), not on a schedule. |
| [0036](0036-beszel-notification-url-no-env-var-support.md) | Accepted | Beszel's notification URL (shoutrrr) has no environment-variable expansion anywhere in its source or the vendored shoutrrr fork — confirmed by reading `henrygd/beszel` directly. The Telegram token stays hand-typed into the web UI, DB-resident, same category as Beszel's KEY/TOKEN bootstrap. |

`docs/vm-provisioning.md` is this repo's other major architecture
decision (the OpenTofu/Ansible ownership boundary) — it predates this
directory and already documents itself as a design record, so it's
left where it is rather than moved. Once OpenTofu work actually lands,
new decisions from that effort belong here as regular numbered ADRs.
