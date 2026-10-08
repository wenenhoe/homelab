---
id: ADR-0047
revision: 0
type: adr
title: First-credential bootstrap for automated processes
short: First-credential bootstrap
solution: Client-certificate login for the operator host from a dedicated step-ca provisioner, response-wrapped one-time handoff for automation identities, and no OpenBao identity on any other host
summary: How the first credential reaches a process that needs it, without a human typing it or a permanent orchestrator relaying secrets.
topic: secrets-store
status: approved
related: [ADR-0020, ADR-0026, ADR-0036, ADR-0043, ADR-0044, ADR-0045, ADR-0049, ADR-0073]
---

# 0047. First-credential bootstrap for automated processes

## Problem

How the first credential reaches a process that needs it, without a human typing it or a permanent orchestrator relaying secrets.

## Context

**Who holds an OpenBao identity today.** Only the operator host (`controller` in the inventory), through the `secrets` role, `rotate-secret.yaml` and the `tools/` scripts that read the credential cache or save a snapshot; the `r2-read-watcher` AppRole on `security`; and `vault-bootstrap`, used interactively. Every other host receives secrets pushed by Ansible: `bootstrap-secrets.yaml` runs the `secrets` role on `localhost` and propagates `secrets_generated` onto each host, so no other host authenticates to OpenBao.

**How the first credential reaches those identities today.** Each answer was reasoned for its own script, and none is a single deliberate one:

- `controller`'s AppRole `role_id` and `secret_id` are files in `SECRETS_DIR` on the operator host (`read_bootstrap_file` in `tools/utils/repo.py`), kept outside OpenBao because they cannot live in the thing they unlock.
- `tools/openbao_utils/bao_session.py` and `snapshot-push.sh` read a `secret_id` from a hidden prompt into memory, never a file.
- `rclone.conf` files holding real B2, R2 and OCI keys are rendered by `cloud_sync` and `restore_discovery`.
- `tools/utils/repo.py`'s `fetch_root_cert()` uses an SSH key to reach `security`.
- Beszel's KEY and TOKEN and [ADR 0036](../0036-beszel-notification-configuration/revision-000.md)'s Telegram webhook are typed into a web UI and live only in Beszel's own database.

[ADR 0046](../0046-python-client-for-s3-compatible-storage/revision-000.md) met the same problem from another side: swapping `rclone` for `boto3` and `hvac` relocates which secret sits on disk and does not remove one.

**What is planned.** The CD agent gets its own CIDR-bound AppRoles ([ADR 0020 revision 1](../0020-automation-identity-and-access-scope/revision-001.md)), and [`cd-agent-controller-approle-retirement.md`](../../projects/cd-agent-controller-approle-retirement.md) deletes `controller`'s standing AppRole. Neither says how the operator host then authenticates to mint a short-lived token.

**Off-site hosts.** [ADR 0049](../0049-monitoring-that-survives-loss-of-the-site/revision-000.md)'s GCP host and [ADR 0045](../0045-security-event-collection-and-alerting/revision-000.md)'s OCI host run on a provider's hardware and have a route back into the lab over the tailnet. Each of those records is gated on this one being `approved` before any production credential goes onto its host, and [ADR 0073](../0073-how-provisioning-authenticates-to-the-off-site-cloud/revision-000.md) names this record as the home for the credentials such a host holds.

**What a scratch run showed.** Against OpenBao 2.7.0 and step-ca 0.30.2, the versions pinned in `docker/openbao/compose.yaml.j2` and `docker/step-ca/compose.yaml.j2`, with the repo's listener stanza (only the certificate and key files set), a CA initialized as `docker/step-ca/scripts/entrypoint.sh` does, and the repo's own `vault-bootstrap.hcl` (31 checks, all passing):

- OpenBao documents a `cert` auth method ([openbao.org](https://openbao.org/docs/auth/cert/)). A certificate issued with `step_ca_cert`'s own `step ca certificate` flags logs in when the step-ca root is registered on the role and the leaf-plus-intermediate `fullchain.pem` is presented. The listener needed no change to request client certificates. The token carried only the role's policies and TTL.
- A different common name, the same name signed by another CA, and no certificate are refused. A leaf without the client-authentication key usage is refused with `x509: certificate specifies an incompatible key usage`; step-ca's default leaf template carries it.
- A certificate renewed with `step ca renew --force`, as `cert-renewer@` does, logs in again, `token_bound_cidrs` on the role is enforced, and plain-token clients are unaffected.
- The `cert` method trusts the CA root and a common name, not the provisioner that signed. The existing provisioner's password is `step-ca-provisioner-password`, stored under `hosts/all/step-ca`, which `controller` and `cd-agent-deploy` can read, and one JWK provisioner signs any common name. `step_ca_cert` itself issues server certificates inside an app's Docker volume and cannot be reused for a client certificate on the host.
- A second provisioner whose template stamps `OU=openbao-operator` and the client-authentication usage, with a role requiring that unit, accepts the second provisioner's certificate, refuses the same common name from the original provisioner, refuses an attempt to set the unit through the original provisioner (whose certificate comes back with no unit), and keeps working after renewal.
- `vault-bootstrap`'s policy as it stands in the repo can read a role's `role-id` and request a response-wrapped `secret_id`, and the wrapping call does not contain the value. It cannot read an application secret. A wrapping token supplied on stdin unwraps once and the unwrapped `secret_id` logs in from the bound address. A second unwrap fails with `wrapping token is not valid or does not exist`.

## Decision

- **The operator host logs in with a client certificate.** It authenticates to OpenBao's `cert` method and receives a short-lived token, holding no AppRole `secret_id`. The certificate comes from a second step-ca JWK provisioner whose template stamps the organizational unit `openbao-operator` and the client-authentication usage. The `cert` role requires the common name, that unit, and the operator host's fixed address (`token_bound_cidrs`).
- **That provisioner's password is never stored in OpenBao.** It is held offline like a break-glass credential, typed once to issue the first certificate, and not needed again: renewal is over mTLS with `step ca renew --force`. The provisioner is added to the CA by hand, once, with its template checked in, as the OpenBao policies are applied by hand elsewhere in this repo.
- **An automation identity's `secret_id` is handed over response-wrapped.** The operator host requests it through `vault-bootstrap` ([ADR 0020 revision 1](../0020-automation-identity-and-access-scope/revision-001.md)). The wrapping token travels over the SSH session the operator host already has to the target for provisioning ([ADR 0044](../0044-prod-automation-trigger-and-execution/revision-000-c.md)), as the remote command's stdin and never as an argument another process could read. It is unwrapped once, on the target, straight into the job user's `0400` file. A second unwrap fails, so an interception shows up as a failure instead of a quietly stolen, reusable credential.
- **No other host holds an OpenBao identity.** A host that is not an automation identity receives the secrets in its own catalog scope, pushed by Ansible through the same `secrets` role and deploy path as an on-prem host.
- **Off-site hosts follow the same rule.** They hold no OpenBao identity and receive only the secrets their own role needs. A compromised off-site host exposes those secrets and a tailnet route back into the lab.

## Alternatives considered

- **Reusing the existing provisioner for client certificates.** Its password is readable by the deploy role, and it signs any common name, so only the role's address binding would stop a holder of that role from logging in as the operator.
- **A second provisioner without the unit requirement.** The `cert` method does not look at the provisioner, so the original one could still mint the operator's common name. The role has to require what only the new provisioner's template can produce.
- **The operator host requesting the wrapped `secret_id` with its own certificate or AppRole.** `controller`'s policy has no `auth/approle` capability, and `vault-bootstrap` is the narrower identity that has exactly it.
- **An AppRole on each off-site host with a wrapped handoff.** It puts a durable OpenBao identity on hardware the lab does not own, and nothing those hosts do needs OpenBao when the secrets they need can be pushed.
- **A local OS secret store** (`systemd-creds`, a TPM-sealed secret, an OS keyring). It keeps the credential out of a plain file at the cost of tying it to one host's hardware, which cuts against this repo's preference for hosts that can be re-created.
- **Accepting that a human types it in when needed.** That reverses the documented plan of the CD agent automating it, and the decision above gives that automation a mechanism.
- **Attestation-based issuance** (SPIFFE/SPIRE style), signing a request on something intrinsic to the host. It is the ceiling above this decision and heavier than a handful of self-managed hosts needs.

## Consequences

- A certificate and key on the operator host is itself a standing credential, renewable for as long as renewal runs. It is narrower than a `secret_id`: bound to a name, a unit and an address, and expiring unless renewed. If renewal lapses, re-issuing it needs the offline password.
- The second provisioner lives in the CA's own configuration, and `docker/step-ca/scripts/entrypoint.sh` initializes only when that configuration does not exist. A rebuilt `data` volume loses it, and it has to be added again by hand.
- `vault-bootstrap` stays a standing AppRole used interactively with a `secret_id` typed at a hidden prompt.
- This record's approval satisfies the claims in ADR 0049 and ADR 0045 that name it. It does not satisfy their separate gate that a hardening pass for the off-site host exists before it holds credentials.
- The tailnet route from an off-site host back into the lab is bounded by the tailnet's access rules, which this record does not set.
- When `controller`'s AppRole is retired, its `role_id` and `secret_id` files in `SECRETS_DIR` go with it.

## Invariants

- A host that is not an automation identity holds no OpenBao credential.
- The `cert` role accepts only a certificate that the second provisioner's template can produce, and only from the operator host's address.
- The second provisioner's password is never stored in OpenBao.
- A response-wrapped value is unwrapped once and carried on stdin, never as an argument.

## Non-goals

- How Tofu authenticates to the cloud account ([ADR 0073](../0073-how-provisioning-authenticates-to-the-off-site-cloud/revision-000.md)) and where Tofu's own credentials live ([ADR 0048](../0048-where-tofu-credentials-live/revision-000.md)).
- What each AppRole may read ([ADR 0020 revision 1](../0020-automation-identity-and-access-scope/revision-001.md)).
- Hardening any host. On-prem hosts are covered one area at a time by [ADR 0043](../0043-host-os-hardening-baseline/revision-000.md), and the off-site hosts' pass is a separate gate in ADR 0049 and ADR 0045.
- The tailnet's access rules for off-site hosts.
- Attestation-based issuance.

## Validation

[`cd-agent-controller-approle-retirement.md`](../../projects/cd-agent-controller-approle-retirement.md) verifies that the `cert` role refuses the operator's common name when the original provisioner signs it. [`cd-agent-approles.md`](../../projects/cd-agent-approles.md) verifies that a wrapped `secret_id` unwraps once and that a second unwrap fails. A grep of the roles, playbooks, `docker/` and `tools/` for AppRole use finds only the identities listed in Context.

## Reconsideration triggers

- A host other than an automation identity needs to read OpenBao directly.
- A second person or host needs operator access, so the single common name and address binding no longer fit.
- The operator host loses its fixed address.
- Attestation-based issuance becomes affordable for the hosts this lab runs.
