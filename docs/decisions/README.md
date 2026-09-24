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
file per solution tried for it. The lineage's number identifies the
problem and is never reused. The title names the problem, never the
solution ("Secret storage", not "OpenBao, not a file cache"); each
revision's `solution:` field carries the answer. Use
[`TEMPLATE.md`](TEMPLATE.md).

Files are `revision-NNN.md`, numbered by **generation**: `revision-000.md`
is the original solution and `revision-001.md` is what replaces it.
Solutions that compete to fill the same generation are lettered
**candidates** — `revision-000-a.md`, `revision-000-b.md` — because
neither revises the other. Letters run a, b, c… with none missing and are
required only once a generation has more than one candidate (a lone one is
unlettered or `a`). A revision is named in `supersedes`, `superseded_by`,
and a project's `decision:` by its label: `0`, or `0-b` for a lettered
candidate.

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
- Competing candidates in one generation stay `working` until one is
  `approved`; the others are then `abandoned`, because approval
  authorizes one design and never two. Letters record the order the
  candidates were written in, not which is preferred.

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

## Lineages

### Deployment & platform

| ADR | Problem | Current solution | Status | Notes |
| :--- | :--- | :--- | :--- | :--- |
| [0001](0001-host-configuration-reproducible-from-repo/revision-000.md) | **Host configuration reproducible from the repo** — Every host converges from what's checked into the repo, so a fresh host needs no manual setup. | Ansible playbooks and roles as the only way any host is configured | Accepted | Related: [0002](0002-reverse-proxy-configuration-reproducible-from-repo/revision-000.md), [0057](0057-managing-the-maintainer-workstation-from-the-repo/revision-000.md) |
| [0004](0004-container-access-to-the-docker-api/revision-000.md) | **Container access to the Docker API** — Containers that need the Docker API get only the capabilities they use, never control of every container on the host. | A per-consumer docker-socket-proxy sidecar, never the raw socket | Accepted | Related: [0009](0009-internal-service-certificate-issuance-and-renewal/revision-000.md), [0043](0043-host-os-hardening-baseline/revision-000.md), [0052](0052-molecule-runtime-without-host-privilege/revision-000.md) |
| [0005](0005-persistent-container-state-and-host-permissions/revision-000.md) | **Persistent container state and host permissions** — App state survives container replacement without UID/permission friction and can be backed up generically. | Docker-managed named volumes, populated by Ansible | Accepted | Related: [0035](0035-container-orchestration-platform/revision-000.md) |
| [0035](0035-container-orchestration-platform/revision-000.md) | **Container orchestration platform** — Whether a single-host homelab runs an orchestrator, given the resource cost on 6 cores and 32 GB. | Docker Compose with Ansible; no Kubernetes for now | Accepted | Related: [0005](0005-persistent-container-state-and-host-permissions/revision-000.md), [0051](0051-coding-agent-execution-isolation/revision-000.md) |
| [0040](0040-dns-for-tofu-provisioned-vms/revision-000.md) | **DNS for Tofu-provisioned VMs** — How Tofu-provisioned VMs get internal A records when their IPs are fixed at provision time. | A second, dedicated BIND9 on security, fed by the Tofu-to-Ansible inventory generator | Working | Related: [0053](0053-network-reach-of-the-coding-agent-host/revision-000.md) |
| [0044](0044-prod-automation-trigger-and-execution/revision-000-a.md) | **Trigger and execution of prod-touching automation** — How deploys and rotations that touch prod are triggered and run, without GitHub dispatching a job to a prod-reaching host. | Undecided between: (000-a) A pull-based CD agent polling origin/main, not a GitHub-dispatched runner; or (000-b) A private, LAN-only Gitea or Forgejo instance with Actions and a runner on the agent host | Working (000-a), Working (000-b) | Related: [0020](0020-automation-identity-and-access-scope/revision-000.md), [0023](0023-reusing-cloud-credential-logic-with-the-secrets-store/revision-000.md), [0050](0050-agent-authored-changes-reaching-production/revision-000.md), [0054](0054-managing-an-untrusted-host-from-the-cd-agent/revision-000.md), [0056](0056-credentials-held-by-the-maintainer-workstation/revision-000.md), [0058](0058-where-operator-work-runs/revision-000.md), [0061](0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md) |
| [0050](0050-agent-authored-changes-reaching-production/revision-000.md) | **Agent-authored changes reaching production** — How changes written by an untrusted coding agent reach main without any credential in the agent's environment being able to alter what the CD agent deploys. | The coding-agent host holds no push credential; the maintainer fetches from it and pushes from the workstation | Approved | Related: [0020](0020-automation-identity-and-access-scope/revision-000.md), [0037](0037-decision-and-project-documentation-workflow/revision-001.md), [0044](0044-prod-automation-trigger-and-execution/revision-000-b.md), [0055](0055-maintainer-client-access-to-the-coding-agent-host/revision-000.md), [0056](0056-credentials-held-by-the-maintainer-workstation/revision-000.md), [0061](0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md) |
| [0057](0057-managing-the-maintainer-workstation-from-the-repo/revision-000.md) | **Managing the maintainer workstation from the repo** — How the maintainer workstation's configuration becomes reproducible from the repo though it is a desktop a person uses interactively. | Ansible configures it after a manual OS install, applied from the operator host over SSH, with a TLS remote desktop for access | Working | Related: [0001](0001-host-configuration-reproducible-from-repo/revision-000.md), [0054](0054-managing-an-untrusted-host-from-the-cd-agent/revision-000.md), [0055](0055-maintainer-client-access-to-the-coding-agent-host/revision-000.md), [0056](0056-credentials-held-by-the-maintainer-workstation/revision-000.md), [0058](0058-where-operator-work-runs/revision-000.md) |
| [0058](0058-where-operator-work-runs/revision-000.md) | **Where operator work runs** — Where Ansible, Tofu, the tools utilities, and break-glass access run, on a host that holds the infrastructure credentials and handles no untrusted content. | A small headless VM in VLAN 30, reachable over SSH only from the maintainer's laptop, that becomes the controller | Working | Related: [0013](0013-secret-storage/revision-001.md), [0020](0020-automation-identity-and-access-scope/revision-000.md), [0044](0044-prod-automation-trigger-and-execution/revision-000-b.md), [0047](0047-first-credential-bootstrap-for-automated-processes/revision-000.md), [0048](0048-where-tofu-credentials-live/revision-000.md), [0053](0053-network-reach-of-the-coding-agent-host/revision-000.md), [0054](0054-managing-an-untrusted-host-from-the-cd-agent/revision-000.md), [0056](0056-credentials-held-by-the-maintainer-workstation/revision-000.md), [0057](0057-managing-the-maintainer-workstation-from-the-repo/revision-000.md), [0059](0059-where-the-tailnet-policy-is-defined/revision-000.md) |

### Ingress, TLS & PKI

| ADR | Problem | Current solution | Status | Notes |
| :--- | :--- | :--- | :--- | :--- |
| [0002](0002-reverse-proxy-configuration-reproducible-from-repo/revision-000.md) | **Reverse-proxy configuration reproducible from the repo** — Proxy routes, TLS, and access rules live in a checked-in file, not a UI-backed database, so a rebuilt proxy needs no manual setup. | Caddy, configured by a checked-in Caddyfile | Accepted | Related: [0001](0001-host-configuration-reproducible-from-repo/revision-000.md) |
| [0003](0003-certificate-issuance-for-proxied-apps/revision-000.md) | **Certificate issuance for proxied apps** — How Caddy-proxied apps get TLS certificates, and whether each app hostname is exposed in public Certificate Transparency logs. | One wildcard certificate per host (tinyauth a deliberate exception) | Accepted (original) | Revision 1 working |
| [0007](0007-internal-ca-initialization-and-identity-persistence/revision-000.md) | **Internal CA initialization and identity persistence** — How step-ca is initialized idempotently, with independent CA and provisioner passwords, a settable claim duration, and its identity kept outside the image. | A custom entrypoint running step ca init, gated on the config existing | Accepted | Related: [0008](0008-internal-certificate-lifetime/revision-000.md), [0009](0009-internal-service-certificate-issuance-and-renewal/revision-000.md) |
| [0008](0008-internal-certificate-lifetime/revision-000.md) | **Internal certificate lifetime** — How long certificates from the internal CA live, given the renewal automation that exists. | 720h default provisioner claim duration | Accepted (original) | Revision 1 working; Related: [0007](0007-internal-ca-initialization-and-identity-persistence/revision-000.md) |
| [0009](0009-internal-service-certificate-issuance-and-renewal/revision-000.md) | **Internal service certificate issuance and renewal** — How a service that terminates its own TLS (lldap's LDAPS, decided here) gets and renews a certificate from the internal CA, without an external ACME provider. | step-ca client roles with systemd renewal timers | Accepted | Related: [0004](0004-container-access-to-the-docker-api/revision-000.md), [0007](0007-internal-ca-initialization-and-identity-persistence/revision-000.md) |

### Secrets store

| ADR | Problem | Current solution | Status | Notes |
| :--- | :--- | :--- | :--- | :--- |
| [0013](0013-secret-storage/revision-001.md) | **Secret storage** — Where the repo's secrets and credentials live, and who and what can read them. | OpenBao as a standing secrets store | Accepted (revision 1) | Related: [0017](0017-recovering-the-secrets-store-from-total-loss/revision-000.md), [0048](0048-where-tofu-credentials-live/revision-000.md), [0056](0056-credentials-held-by-the-maintainer-workstation/revision-000.md), [0058](0058-where-operator-work-runs/revision-000.md); Formerly ADR-0027 |
| [0017](0017-recovering-the-secrets-store-from-total-loss/revision-000.md) | **Recovering the secrets store from total loss** — OpenBao can be rebuilt from nothing, so nothing needed to fetch its own backup lives only inside it. | Recovery-critical secrets stay outside the store permanently | Accepted | Related: [0006](0006-offsite-backup-credential-blast-radius/revision-000.md), [0013](0013-secret-storage/revision-001.md), [0018](0018-unsealing-the-secrets-store-after-restart/revision-000.md), [0019](0019-openbao-offsite-snapshot-path/revision-000.md), [0020](0020-automation-identity-and-access-scope/revision-000.md) |
| [0018](0018-unsealing-the-secrets-store-after-restart/revision-000.md) | **Unsealing the secrets store after restart** — How OpenBao is unsealed after a restart without adding a second offline recovery credential. | Manual Shamir key shares | Accepted | Related: [0017](0017-recovering-the-secrets-store-from-total-loss/revision-000.md), [0048](0048-where-tofu-credentials-live/revision-000.md) |
| [0020](0020-automation-identity-and-access-scope/revision-000.md) | **Automation identity and access scope** — Which identities may read and write which secret paths, given one automation consumer today. | One broad AppRole for controller | Accepted (original) | Revision 1 working; Related: [0017](0017-recovering-the-secrets-store-from-total-loss/revision-000.md), [0021](0021-secret-path-layout-for-secrets-with-no-host-owner/revision-000.md), [0023](0023-reusing-cloud-credential-logic-with-the-secrets-store/revision-000.md), [0024](0024-r2-admin-token-custody/revision-000.md), [0026](0026-detecting-reads-of-high-value-secrets/revision-000.md), [0043](0043-host-os-hardening-baseline/revision-000.md), [0044](0044-prod-automation-trigger-and-execution/revision-000-b.md), [0048](0048-where-tofu-credentials-live/revision-000.md), [0050](0050-agent-authored-changes-reaching-production/revision-000.md), [0053](0053-network-reach-of-the-coding-agent-host/revision-000.md), [0054](0054-managing-an-untrusted-host-from-the-cd-agent/revision-000.md), [0056](0056-credentials-held-by-the-maintainer-workstation/revision-000.md), [0058](0058-where-operator-work-runs/revision-000.md), [0061](0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md), [0062](0062-automation-identity-for-the-agent-based-reviewer/revision-000.md) |
| [0021](0021-secret-path-layout-for-secrets-with-no-host-owner/revision-000.md) | **Secret path layout for secrets with no host owner** — Where secrets that no single host owns are stored, inside the existing access grant. | `hosts/all/<concern>/*` under the existing `hosts/` prefix | Accepted | Related: [0020](0020-automation-identity-and-access-scope/revision-000.md) |
| [0022](0022-controller-trust-in-the-secrets-store-tls/revision-000.md) | **Controller trust in the secrets store's TLS certificate** — How the controller verifies OpenBao's TLS certificate without skip-verify or a committed copy of the CA. | The step-ca root certificate fetched fresh on every run | Accepted | Related: [0034](0034-operator-access-to-the-openbao-cli/revision-000.md) |
| [0025](0025-admin-capability-without-a-standing-root-token/revision-000.md) | **Admin capability without a standing root token** — New Vault policies and AppRoles can be created without keeping a permanent root token. | Re-init with a standing narrow vault-bootstrap AppRole | Accepted | Related: [0026](0026-detecting-reads-of-high-value-secrets/revision-000.md) |
| [0026](0026-detecting-reads-of-high-value-secrets/revision-000.md) | **Detecting reads of high-value secrets** — Every read of the R2 admin token's path is visible and raises an alert. | A declarative stdout audit device plus a least-privilege watcher | Accepted | Narrowed by [0045](0045-security-event-collection-and-alerting/revision-000.md); Related: [0020](0020-automation-identity-and-access-scope/revision-000.md), [0024](0024-r2-admin-token-custody/revision-000.md), [0025](0025-admin-capability-without-a-standing-root-token/revision-000.md), [0043](0043-host-os-hardening-baseline/revision-000.md), [0047](0047-first-credential-bootstrap-for-automated-processes/revision-000.md), [0048](0048-where-tofu-credentials-live/revision-000.md) |
| [0030](0030-openbao-client-implementation-in-repo-python/revision-000.md) | **OpenBao client implementation in repo Python** — Internal Python that talks to OpenBao or over SSH shares one client approach instead of hand-rolled duplicates. | hvac for Vault and paramiko for SSH | Accepted | Related: [0029](0029-cloud-provider-api-client-library/revision-000.md), [0031](0031-where-repo-tooling-lives/revision-000.md), [0034](0034-operator-access-to-the-openbao-cli/revision-000.md) |
| [0047](0047-first-credential-bootstrap-for-automated-processes/revision-000.md) | **First-credential bootstrap for automated processes** — How the first credential reaches a process that needs it, without a human typing it or a permanent orchestrator relaying secrets. | Leaning: mTLS for the controller's own auth, response wrapping for one-time handoff | Working | Related: [0026](0026-detecting-reads-of-high-value-secrets/revision-000.md), [0036](0036-beszel-notification-configuration/revision-000.md), [0049](0049-monitoring-that-survives-loss-of-the-site/revision-000.md), [0056](0056-credentials-held-by-the-maintainer-workstation/revision-000.md), [0058](0058-where-operator-work-runs/revision-000.md) |
| [0048](0048-where-tofu-credentials-live/revision-000.md) | **Where Tofu's own credentials live** — Where the Proxmox and OPNsense API credentials and Tofu's state-backend credential live, given the store may be what is being provisioned. | Undecided: the existing OpenBao, file-based separate secrets, or a dedicated OpenBao instance | Working | Related: [0013](0013-secret-storage/revision-001.md), [0018](0018-unsealing-the-secrets-store-after-restart/revision-000.md), [0020](0020-automation-identity-and-access-scope/revision-000.md), [0026](0026-detecting-reads-of-high-value-secrets/revision-000.md), [0038](0038-iac-misconfiguration-scanning/revision-000.md), [0054](0054-managing-an-untrusted-host-from-the-cd-agent/revision-000.md), [0056](0056-credentials-held-by-the-maintainer-workstation/revision-000.md), [0058](0058-where-operator-work-runs/revision-000.md), [0059](0059-where-the-tailnet-policy-is-defined/revision-000.md) |

### Cloud credentials

| ADR | Problem | Current solution | Status | Notes |
| :--- | :--- | :--- | :--- | :--- |
| [0014](0014-r2-rotation-credential-cannot-be-narrowed/revision-000.md) | **R2 rotation credential that can't be narrowed** — Cloudflare can't mint a narrower delegate for R2's rotation credential, so its blast radius is accepted and contained. | Cache the R2 admin token as the rotation credential, accepted as master-equivalent | Accepted | Related: [0010](0010-preventing-homelab-side-deletion-of-offsite-copies/revision-000.md), [0015](0015-cloud-credential-expiry/revision-000.md), [0023](0023-reusing-cloud-credential-logic-with-the-secrets-store/revision-000.md), [0024](0024-r2-admin-token-custody/revision-000.md) |
| [0015](0015-cloud-credential-expiry/revision-000.md) | **Cloud credential expiry** — Every cloud leaf credential and rotation key expires, and something notices before it does. | Native expiry where a provider has it, self-tracked timestamps where not | Accepted | Narrowed by [0016](0016-oci-credential-creation-and-expiry/revision-000.md); Related: [0014](0014-r2-rotation-credential-cannot-be-narrowed/revision-000.md), [0059](0059-where-the-tailnet-policy-is-defined/revision-000.md) |
| [0016](0016-oci-credential-creation-and-expiry/revision-000.md) | **OCI credential creation and expiry** — How OCI keys are minted and how their expiry is set and tracked, since the classic API has no expiry field. | Identity Domains SCIM with a Confidential Application's OAuth2 client credentials | Accepted | Related: [0023](0023-reusing-cloud-credential-logic-with-the-secrets-store/revision-000.md), [0029](0029-cloud-provider-api-client-library/revision-000.md), [0041](0041-testing-the-oci-classic-iam-bootstrap/revision-000.md) |
| [0023](0023-reusing-cloud-credential-logic-with-the-secrets-store/revision-000.md) | **Reusing cloud-credential logic with the secrets store** — How the existing per-provider credential logic persists its output in OpenBao without being rebuilt. | Repoint the existing scripts at OpenBao KV v2; no native plugin | Accepted | Related: [0014](0014-r2-rotation-credential-cannot-be-narrowed/revision-000.md), [0016](0016-oci-credential-creation-and-expiry/revision-000.md), [0020](0020-automation-identity-and-access-scope/revision-000.md), [0024](0024-r2-admin-token-custody/revision-000.md), [0044](0044-prod-automation-trigger-and-execution/revision-000-b.md) |
| [0024](0024-r2-admin-token-custody/revision-000.md) | **R2 admin token custody** — Where the R2 admin token lives and who hears about a read, given it can be cached but never minted automatically. | In OpenBao under one path, with a per-read alert | Accepted | Related: [0014](0014-r2-rotation-credential-cannot-be-narrowed/revision-000.md), [0020](0020-automation-identity-and-access-scope/revision-000.md), [0023](0023-reusing-cloud-credential-logic-with-the-secrets-store/revision-000.md), [0026](0026-detecting-reads-of-high-value-secrets/revision-000.md) |
| [0029](0029-cloud-provider-api-client-library/revision-000.md) | **Cloud-provider API client library** — How tools/cloud_credentials calls B2, R2, and OCI, weighing hand-rolled requests against official SDKs. | Official SDKs for OCI SCIM and B2; raw requests for R2 and OCI classic IAM | Accepted | Related: [0016](0016-oci-credential-creation-and-expiry/revision-000.md), [0030](0030-openbao-client-implementation-in-repo-python/revision-000.md), [0046](0046-python-client-for-s3-compatible-storage/revision-000.md) |
| [0046](0046-python-client-for-s3-compatible-storage/revision-000.md) | **Python client for S3-compatible object storage** — Which client Python code uses to talk to S3-compatible storage, and where rclone stays. | Leaning: boto3 for the single-object verify call; rclone stays for bulk copy and restore | Working | Related: [0010](0010-preventing-homelab-side-deletion-of-offsite-copies/revision-000.md), [0029](0029-cloud-provider-api-client-library/revision-000.md) |

### Backup & recovery

| ADR | Problem | Current solution | Status | Notes |
| :--- | :--- | :--- | :--- | :--- |
| [0006](0006-offsite-backup-credential-blast-radius/revision-000.md) | **Offsite backup credential blast radius** — A compromised app host must never reach a cloud credential or another host's backup archives. | Cloud credentials only on storage; per-host, prefix-scoped SeaweedFS identities | Accepted | Related: [0010](0010-preventing-homelab-side-deletion-of-offsite-copies/revision-000.md), [0017](0017-recovering-the-secrets-store-from-total-loss/revision-000.md) |
| [0010](0010-preventing-homelab-side-deletion-of-offsite-copies/revision-000.md) | **Preventing homelab-side deletion of offsite copies** — A compromised or misbehaving on-prem host must not be able to delete or overwrite the offsite backup copy. | rclone copy, never sync, plus provider-native retention | Accepted | Related: [0006](0006-offsite-backup-credential-blast-radius/revision-000.md), [0014](0014-r2-rotation-credential-cannot-be-narrowed/revision-000.md), [0042](0042-monitoring-that-survives-loss-of-the-homelab/revision-000.md), [0046](0046-python-client-for-s3-compatible-storage/revision-000.md), [0049](0049-monitoring-that-survives-loss-of-the-site/revision-000.md) |
| [0012](0012-verifying-backups-actually-land/revision-000.md) | **Verifying backups actually land** — Something verifies every app's backups actually reach SeaweedFS, not just that the schedule ran. | An hourly freshness check on every backup_agent host | Accepted | — |
| [0019](0019-openbao-offsite-snapshot-path/revision-000.md) | **OpenBao offsite snapshot path** — How OpenBao's encrypted raft snapshot reaches the offsite copy without depending on the app-backup pipeline. | A direct rclone push, outside backup_agent and cloud_sync | Accepted | Narrowed by [0034](0034-operator-access-to-the-openbao-cli/revision-000.md); Related: [0017](0017-recovering-the-secrets-store-from-total-loss/revision-000.md) |

### Monitoring & alerting

| ADR | Problem | Current solution | Status | Notes |
| :--- | :--- | :--- | :--- | :--- |
| [0011](0011-alert-routing-and-noise/revision-000.md) | **Alert routing and noise** — Alerts for different concerns stay distinguishable, so a real failure isn't lost in routine notifications. | A Telegram group chat with a topic per concern | Accepted | — |
| [0036](0036-beszel-notification-configuration/revision-000.md) | **Beszel notification configuration** — How Beszel's Telegram channel is configured, given its notification URL supports no environment variables. | The token hand-typed into the web UI, DB-resident | Accepted | Related: [0047](0047-first-credential-bootstrap-for-automated-processes/revision-000.md) |
| [0042](0042-monitoring-that-survives-loss-of-the-homelab/revision-000.md) | **Monitoring that survives loss of the monitoring host** — Beszel and Kuma keep running, and alerting, when the host they run on fails. | Bring the Tailscale subnet router under management, then run monitoring on a dedicated on-prem host | Approved | Related: [0010](0010-preventing-homelab-side-deletion-of-offsite-copies/revision-000.md), [0049](0049-monitoring-that-survives-loss-of-the-site/revision-000.md) |
| [0049](0049-monitoring-that-survives-loss-of-the-site/revision-000.md) | **Monitoring that survives loss of the site** — Something outside the site notices when the whole homelab or its connectivity goes down. | Relocate monitoring to a GCP e2-micro, reached by extending VM 202's Tailscale subnet route | Working | Related: [0010](0010-preventing-homelab-side-deletion-of-offsite-copies/revision-000.md), [0042](0042-monitoring-that-survives-loss-of-the-homelab/revision-000.md), [0047](0047-first-credential-bootstrap-for-automated-processes/revision-000.md), [0059](0059-where-the-tailnet-policy-is-defined/revision-000.md) |

### Repository & tooling

| ADR | Problem | Current solution | Status | Notes |
| :--- | :--- | :--- | :--- | :--- |
| [0031](0031-where-repo-tooling-lives/revision-000.md) | **Where repo tooling lives** — Controller-side utilities live where their domain says, not where they happened to be written. | A root tools/ directory split by domain | Accepted | Narrowed by [0032](0032-where-openbao-utility-scripts-live/revision-000.md); Related: [0030](0030-openbao-client-implementation-in-repo-python/revision-000.md) |
| [0032](0032-where-openbao-utility-scripts-live/revision-000.md) | **Where OpenBao utility scripts live** — Whether OpenBao utility scripts belong with the deploy playbooks or with the standalone tools. | Consolidated in tools/openbao_utils/ | Accepted | — |
| [0033](0033-where-the-interactive-bao-session-runs/revision-000.md) | **Where the interactive bao session runs** — Where bao_session.py runs, given a relay to security never had a working local half. | controller only; the SSH relay to security dropped | Accepted | Related: [0034](0034-operator-access-to-the-openbao-cli/revision-000.md) |
| [0034](0034-operator-access-to-the-openbao-cli/revision-000.md) | **Operator access to the OpenBao CLI** — How operators reach the bao CLI, replacing four overlapping docker-exec and alias patterns. | A native bao binary on security and controller | Accepted | Related: [0022](0022-controller-trust-in-the-secrets-store-tls/revision-000.md), [0030](0030-openbao-client-implementation-in-repo-python/revision-000.md), [0033](0033-where-the-interactive-bao-session-runs/revision-000.md) |
| [0041](0041-testing-the-oci-classic-iam-bootstrap/revision-000.md) | **Testing the OCI classic-IAM bootstrap** — How the OCI classic-IAM bootstrap code is tested beyond hand-written mocks. | floci-oci for the classic-IAM surface only; SCIM tests stay hand-mocked | Working | Related: [0016](0016-oci-credential-creation-and-expiry/revision-000.md) |
| [0063](0063-what-the-code-review-image-is-built-from-and-how-it-stays-current/revision-000.md) | **What the code-review image is built from, and how it stays current** — How the image that runs the CodeRabbit CLI is versioned, based, and kept up to date when upstream publishes no machine-readable release list. | Pin the CLI through the installer's own version variable, bump it with Renovate from the release's VERSION file, use an Ubuntu LTS base, and tag every image with its CLI version | Working | Related: [0061](0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md) |

### Security & hardening

| ADR | Problem | Current solution | Status | Notes |
| :--- | :--- | :--- | :--- | :--- |
| [0038](0038-iac-misconfiguration-scanning/revision-000.md) | **IaC misconfiguration scanning** — Which scanner checks Ansible and OpenTofu for misconfiguration, without a separate migration for each. | Trivy for Ansible now; Checkov once OpenTofu code lands, then covering both | Working | Related: [0048](0048-where-tofu-credentials-live/revision-000.md) |
| [0039](0039-intrusion-detection-scope/revision-000.md) | **Intrusion detection scope** — Whether detection lives only on the OPNsense perimeter or also on each VM, without inspecting the lab's own TLS. | Undecided: CrowdSec at the perimeter only, or with per-VM agents | Working | Related: [0053](0053-network-reach-of-the-coding-agent-host/revision-000.md) |
| [0043](0043-host-os-hardening-baseline/revision-000.md) | **Host OS hardening baseline** — A deliberate host-level hardening pass (SSH, sysctl, auditd, mandatory access control), not only per-component least privilege. | Undecided: a third-party baseline, or a hand-picked subset in this repo's own roles | Working | Related: [0004](0004-container-access-to-the-docker-api/revision-000.md), [0020](0020-automation-identity-and-access-scope/revision-000.md), [0026](0026-detecting-reads-of-high-value-secrets/revision-000.md), [0051](0051-coding-agent-execution-isolation/revision-000.md), [0054](0054-managing-an-untrusted-host-from-the-cd-agent/revision-000.md) |
| [0045](0045-security-event-collection-and-alerting/revision-000.md) | **Security event collection and alerting** — Whether purpose-built alerting scripts give way to a security-event pipeline, and where it runs. | Leaning: Wazuh on a dedicated OCI Ampere instance, replacing single-purpose alerting scripts | Working | — |
| [0051](0051-coding-agent-execution-isolation/revision-000.md) | **Coding-agent execution isolation** — What isolates an autonomous coding agent's execution from the rest of the lab, given one Proxmox node shared by every VM. | A dedicated Proxmox VM without nested virtualization, running the agent unprivileged under Claude Code's built-in sandbox | Working | Related: [0035](0035-container-orchestration-platform/revision-000.md), [0043](0043-host-os-hardening-baseline/revision-000.md), [0052](0052-molecule-runtime-without-host-privilege/revision-000.md), [0061](0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md) |
| [0052](0052-molecule-runtime-without-host-privilege/revision-000.md) | **Molecule runtime without host privilege** — How this repo's privileged, systemd-based Molecule fixtures run on the coding-agent host without a container that has host-level root reach. | Undecided: rootless Podman, rootless Docker, or a microVM-private daemon, chosen by spike | Working | Related: [0004](0004-container-access-to-the-docker-api/revision-000.md), [0051](0051-coding-agent-execution-isolation/revision-000.md) |
| [0053](0053-network-reach-of-the-coding-agent-host/revision-000.md) | **Network reach of the coding-agent host** — What the coding-agent host can reach and be reached from, enforced at the firewall rather than on the host. | Its own VLAN, default-deny both ways at OPNsense, egress through a domain-filtering proxy, and a resolver with no internal zones | Working | Related: [0020](0020-automation-identity-and-access-scope/revision-000.md), [0039](0039-intrusion-detection-scope/revision-000.md), [0040](0040-dns-for-tofu-provisioned-vms/revision-000.md), [0055](0055-maintainer-client-access-to-the-coding-agent-host/revision-000.md), [0058](0058-where-operator-work-runs/revision-000.md), [0059](0059-where-the-tailnet-policy-is-defined/revision-000.md) |
| [0054](0054-managing-an-untrusted-host-from-the-cd-agent/revision-000.md) | **Managing an untrusted host from the CD agent** — How a host that runs untrusted code is built and kept patched by a controller holding production credentials, without either side inheriting the other's authority. | Rebuild from the Tofu definition on a schedule, a dedicated key and inventory group, and a management job with its own identity | Working | Related: [0020](0020-automation-identity-and-access-scope/revision-000.md), [0043](0043-host-os-hardening-baseline/revision-000.md), [0044](0044-prod-automation-trigger-and-execution/revision-000-b.md), [0048](0048-where-tofu-credentials-live/revision-000.md), [0057](0057-managing-the-maintainer-workstation-from-the-repo/revision-000.md), [0058](0058-where-operator-work-runs/revision-000.md) |
| [0055](0055-maintainer-client-access-to-the-coding-agent-host/revision-000.md) | **Maintainer client access to the coding-agent host** — How the maintainer drives the agent and reviews its work without the host gaining a path to the workstation's push credential. | One workstation identity, terminal-only SSH to the host on a dedicated key, and review by git fetch and a local diff | Approved | Related: [0037](0037-decision-and-project-documentation-workflow/revision-001.md), [0050](0050-agent-authored-changes-reaching-production/revision-000.md), [0053](0053-network-reach-of-the-coding-agent-host/revision-000.md), [0056](0056-credentials-held-by-the-maintainer-workstation/revision-000.md), [0057](0057-managing-the-maintainer-workstation-from-the-repo/revision-000.md) |
| [0056](0056-credentials-held-by-the-maintainer-workstation/revision-000.md) | **Credentials held by the maintainer workstation** — Which credentials the maintainer workstation holds, so a compromised routine session finds no infrastructure credential to read. | The workstation holds the push credential and the coding-agent host key only; every infrastructure credential moves to the operator host | Approved | Related: [0013](0013-secret-storage/revision-001.md), [0020](0020-automation-identity-and-access-scope/revision-000.md), [0044](0044-prod-automation-trigger-and-execution/revision-000-b.md), [0047](0047-first-credential-bootstrap-for-automated-processes/revision-000.md), [0048](0048-where-tofu-credentials-live/revision-000.md), [0050](0050-agent-authored-changes-reaching-production/revision-000.md), [0055](0055-maintainer-client-access-to-the-coding-agent-host/revision-000.md), [0057](0057-managing-the-maintainer-workstation-from-the-repo/revision-000.md), [0058](0058-where-operator-work-runs/revision-000.md) |
| [0059](0059-where-the-tailnet-policy-is-defined/revision-000.md) | **Where the tailnet policy is defined** — The tailnet ACL policy is a security boundary ADRs 0049, 0053, and 0058 depend on; decide where it is authored and when that changes. | Hand-edited in the console now, with tests as the guard; moves to OpenTofu via the tailscale/tailscale provider once ADR 0048 settles where Tofu's own credentials live | Working | Related: [0015](0015-cloud-credential-expiry/revision-000.md), [0048](0048-where-tofu-credentials-live/revision-000.md), [0049](0049-monitoring-that-survives-loss-of-the-site/revision-000.md), [0053](0053-network-reach-of-the-coding-agent-host/revision-000.md), [0058](0058-where-operator-work-runs/revision-000.md) |
| [0060](0060-tracking-and-managing-code-review-findings-for-a-public-repository/revision-000.md) | **Tracking and managing code-review findings for a public repository** — Where automated code-review findings live, given the repo they describe is public. | A private tracker repo (homelab-security), issues-based, not a mirror of the public repo's code | Approved | Related: [0061](0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md) |
| [0061](0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md) | **Where automated code review runs, and what it may write** — How this repo gets automated code review without any of it becoming visible on this repo's own surfaces, or able to alter it unsupervised. | Both CodeRabbit's PR-diff review and a periodic agent-driven full-repo audit run from homelab-security's own CI, and neither holds a credential that can write to this repo | Approved | Related: [0020](0020-automation-identity-and-access-scope/revision-000.md), [0037](0037-decision-and-project-documentation-workflow/revision-001.md), [0044](0044-prod-automation-trigger-and-execution/revision-000-b.md), [0050](0050-agent-authored-changes-reaching-production/revision-000.md), [0051](0051-coding-agent-execution-isolation/revision-000.md), [0060](0060-tracking-and-managing-code-review-findings-for-a-public-repository/revision-000.md), [0062](0062-automation-identity-for-the-agent-based-reviewer/revision-000.md), [0063](0063-what-the-code-review-image-is-built-from-and-how-it-stays-current/revision-000.md) |
| [0062](0062-automation-identity-for-the-agent-based-reviewer/revision-000.md) | **Automation identity for the agent-based reviewer** — Which credential the periodic full-repo audit agent authenticates with, and whose usage it draws from. | Leaning: CLAUDE_CODE_OAUTH_TOKEN from a Claude Pro/Max subscription, dedicated to automation rather than the personal daily-driver account | Working | Related: [0020](0020-automation-identity-and-access-scope/revision-000.md), [0061](0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md) |

### Documentation & process

| ADR | Problem | Current solution | Status | Notes |
| :--- | :--- | :--- | :--- | :--- |
| [0028](0028-doc-metadata-and-governance/revision-000.md) | **Doc metadata and governance** — How docs carry machine-readable metadata, how index tables stay current, and how NIST alignment is shown without stamping ADRs. | YAML frontmatter, generated indexes, one narrative NIST alignment doc | Accepted | Narrowed by [0037](0037-decision-and-project-documentation-workflow/revision-001.md) |
| [0037](0037-decision-and-project-documentation-workflow/revision-001.md) | **Recording decisions, tracking execution, and keeping docs true** — How why, what-remains, and what-is-true-now are kept apart, extended to close a visibility gap the original method left open. | also_implements: as a validated, non-gating frontmatter field, plus a generated view of open ADRs no project covers | Accepted (revision 1) | Revision 2 approved; Related: [0050](0050-agent-authored-changes-reaching-production/revision-000.md), [0055](0055-maintainer-client-access-to-the-coding-agent-host/revision-000.md), [0061](0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md) |

## Other design records

`docs/vm-provisioning.md` is this repo's other major architecture
decision (the OpenTofu/Ansible ownership boundary) — it predates this
directory and already documents itself as a design record, so it's
left where it is rather than moved. Once OpenTofu work actually lands,
new decisions from that effort belong here as regular lineages.
