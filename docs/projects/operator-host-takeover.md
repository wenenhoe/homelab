---
id: PROJ-operator-host-takeover
title: Operator Host Takeover
type: project
status: not-started
blocked: false
summary: The egress allowlist for VLAN 30, then the controller's toolchain and credentials moved onto the operator host.
decision: ADR-0058/0
plan: draft
super_project: controller-separation
depends_on:
  - project: PROJ-operator-host
    reason: the host, its rules and its role have to exist before the controller can move onto it
  - project: PROJ-coding-agent-egress
    reason: the egress allowlist goes through the proxy that project builds
---

# Operator Host Takeover

Moves the controller off the workstation onto the host [`operator-host.md`](operator-host.md) builds, so the workstation can be stripped ([`vm-401-retirement.md`](vm-401-retirement.md)). Staged because the host's outbound traffic is restricted to an allowlist before it holds any credential, and each credential then moves as a step to prove.

## Scope

The VLAN 30 allowlist on the egress proxy, and moving the toolchain and credentials onto the host: `main-domain`, a freshly issued AppRole secret, the Tofu credentials file and the state backend's two env files ([ADR 0048 (Tofu credentials)](../decisions/0048-where-tofu-credentials-live/revision-000.md), [`state-and-credentials.md`](../topics/infra/tofu/state-and-credentials.md)) and the shared SSH key. Not in scope: building the host ([`operator-host.md`](operator-host.md)), the proxy itself ([`coding-agent-egress.md`](coding-agent-egress.md)), stripping and retiring VM 401 ([`vm-401-retirement.md`](vm-401-retirement.md)), and shrinking the credentials as the CD agent lands ([`cd-agent.md`](cd-agent.md), [`cd-agent-controller-approle-retirement.md`](cd-agent-controller-approle-retirement.md)).

## Decision

Implements [ADR 0058 (Operator work host)](../decisions/0058-where-operator-work-runs/revision-000.md), `working`, so this project is `not-started` until the revision is `approved`. Stage 1 resolves its remaining proxy assumption. The project that closes last sets it `accepted`.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Egress allowlist through the proxy | Not started | A canary in VLAN 30 reaches every allowlisted destination and no other, and ADR 0058 can be `approved` |
| 2 | Move the controller: toolchain, `main-domain`, a freshly issued AppRole secret, the Tofu credentials file, the shared SSH key. No credential moves before Stage 1 | Not started | A deploy in check mode, a `tofu plan`, and an `openbao_utils.shell` login all succeed from the operator host, and then `vault-bootstrap` is bound to the host's address and the lldap web route is limited to it |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] Every operation the controller performs today succeeds from the operator host.
- [ ] Outbound from VLAN 30 reaches only the allowlisted destinations.
- [ ] `vault-bootstrap` accepts a login only from this host's address, set after the first login from it succeeds ([`openbao-vault-bootstrap.md`](../topics/secrets/openbao-vault-bootstrap.md)), and a login from the workstation is refused.
- [ ] The lldap web route accepts requests only from this host's address, through a Caddy `remote_ip` matcher on that route. The address is one variable, shared with the `vault-bootstrap` bind, so the migration changes it once. A request from the workstation is refused.
- [ ] The resulting behavior, including the restore procedure, is described in `docs/topics/infra/operator-host.md`.

## Agent handoff

- **Allowed to change:** not scoped yet; `allowed_paths` is added, in its own change, before an agent implements a stage.
- **Must not change:** other hosts' inventory entries, the `all.vars` SSH key, existing OpenBao policies.
- **Relevant files and interfaces:** `ansible/inventory/inventory.yaml` (the `controller` group), `docs/topics/secrets/openbao-auth.md` (issuing a new AppRole secret), `docs/topics/infra/network-infra.md`.
- **Required checks:** `pre-commit run --all-files`.

## Risks

- This project is on the critical path for stripping the workstation.
- The Tofu credentials file is the only copy of those credentials on the host; moving it means issuing replacements rather than copying the old ones off the workstation.

## Open items

- The restore procedure on this host: import the backup GPG private key for the restore only, then remove it. It belongs in `docs/topics/infra/operator-host.md`.
- The lldap route's allow-list is built once this host answers: until then the address it would name belongs to the workstation, and limiting the route to a host that is not yet in use would lock the directory's web interface out.
- Binding the interim controller AppRole to this host's CIDR until the retirement project deletes it. Cheap, but only worth doing if the retirement is far off.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
