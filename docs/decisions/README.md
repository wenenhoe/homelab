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

Use [`TEMPLATE.md`](TEMPLATE.md) for new entries. Number sequentially;
never renumber or delete a superseded one — mark it `Superseded by
000N` instead, so old links keep resolving.

## Index

| ADR | Status | Decision |
| :--- | :--- | :--- |
| [0001](0001-credential-caching-stage-1-before-secrets-manager.md) | Accepted | Cache rotation/leaf credentials to `ansible/files/secrets/` now; defer a real secrets manager to a later, separately-scoped project. |
| [0002](0002-r2-rotation-token-accepted-as-master-equivalent.md) | Accepted | Cache Cloudflare R2's admin token as the de facto rotation credential, accepting it's master-equivalent (unlike B2's/OCI's narrower rotation keys), because Cloudflare's API structurally can't mint a scoped delegate for it. |
| [0003](0003-lldap-ldaps-cert-via-stepca-not-certbot.md) | Accepted | Issue lldap's LDAPS cert from the internal step-ca via host-level systemd timers, replacing the original certbot + DNS-01 + docker-socket-proxy sidecar pair. |
| [0004](0004-stepca-custom-entrypoint-not-docker-init-vars.md) | Accepted | Run `step ca init` by hand in a custom entrypoint instead of the official image's `DOCKER_STEPCA_INIT_*` auto-init, so the CA and provisioner passwords stay independent and claim duration is settable. |
| [0005](0005-stepca-cert-duration-720h.md) | Accepted, flagged for review | step-ca's default cert lifetime is 720h, not step-ca's own 24h — chosen before renewal automation existed; that automation now exists and the value hasn't been revisited. |
| [0006](0006-cloud-sync-copy-not-sync.md) | Accepted | `cloud_sync` relays to R2/B2/OCI via rclone `copy`, never `sync`, and cloud-side retention stays a provider-native, out-of-band lifecycle rule — the actual mechanism (not IAM scoping) that keeps a compromised on-prem host from touching the offsite copy. |
| [0007](0007-backup-freshness-check-per-host.md) | Accepted | Run backup-freshness checks per host instead of one centralized checker on `storage`, because a centralized checker needs cross-host `hostvars` facts that aren't populated under a partial `--limit` deploy. |
| [0008](0008-caddy-not-nginx-proxy-manager.md) | Accepted | Use Caddy, configured entirely via a checked-in `Caddyfile`, instead of Nginx Proxy Manager's UI/database-backed config. |
| [0009](0009-adopt-ansible-not-manual-deployment.md) | Accepted | Adopt Ansible as the only way any host is configured, replacing manual per-host `docker compose` over SSH. |
| [0010](0010-caddy-wildcard-certs-not-per-app.md) | Accepted, partially applied | Route most apps through one wildcard cert per host instead of one cert per app — flatter config, and avoids exposing individual app hostnames in public Certificate Transparency logs. `tinyauth` is still a deliberate exception. |
| [0011](0011-docker-socket-proxy-not-raw-socket.md) | Accepted | Any container needing Docker API access gets a `docker-socket-proxy` sidecar scoped to exactly the capabilities it needs, never the raw socket — replacing `diun`'s original unrestricted socket mount. |
| [0012](0012-named-volumes-not-bind-mounts.md) | Accepted | Use Docker-managed named volumes instead of bind mounts, to eliminate host/container UID permission friction and enable a generic backup agent; a Kubernetes migration was considered and rejected around the same time for lack of a real multi-machine cluster. |
| [0013](0013-backup-credential-blast-radius-threat-model.md) | Accepted | Threat model for the offsite backup: a compromised app host must never reach a cloud credential or another host's archives. Cloud credentials live only on `storage`; each app host's SeaweedFS identity is scoped to its own prefix. |
| [0014](0014-telegram-topics-not-direct-chat.md) | Accepted | Move alerting from a direct one-on-one bot chat to a group chat with Topics, one topic per concern, so a real failure doesn't get lost in routine notification noise. |
| [0015](0015-credential-expiry-native-where-possible-self-tracked-where-not.md) | Accepted (OCI superseded by 0016) | All 6 leaf credentials and 3 rotation keys/tokens now expire after 90 days — B2/R2 natively, OCI via a self-tracked cache-file timestamp — checked by a systemd user timer on `controller`, not an Ansible role. |
| [0016](0016-oci-expiry-via-scim-not-self-tracked-cache-files.md) | Accepted | OCI leaf-key creation and expiry both move to Identity Domains SCIM, replacing the classic API entirely; the rotation credential (now a Confidential Application's OAuth2 client credentials) keeps self-tracked expiry, since it has no native expiry of its own. |

`docs/vm-provisioning.md` is this repo's other major architecture
decision (the OpenTofu/Ansible ownership boundary) — it predates this
directory and already documents itself as a design record, so it's
left where it is rather than moved. Once OpenTofu work actually lands,
new decisions from that effort belong here as regular numbered ADRs.
