---
id: PROJ-gatehouse
title: "Gatehouse: Landing a Series from the Phone"
type: project
status: not-started
plan: draft
blocked: false
summary: A web console on its own VM that reviews and lands a patch series from the laptop or the phone over the tailnet, with a merge token that lives for one series.
decision: ADR-0114/0
---

# Gatehouse: Landing a Series from the Phone

Builds the console [ADR 0114 (Remote series landing)](../decisions/0114-landing-a-series-from-a-device-other-than-the-laptop/revision-000.md) decides. It is staged because the console needs a seam in `land_series` first, a host with its own network, tag and sign-in, and a move to its own repository once the seam is stable. The plan is a draft until that revision is approved.

## Scope

- A seam in `tools/land_series`: progress events and confirm callbacks in place of the terminal, and the stop list and checks as configuration of the target repository. The CLI behaves as before.
- The console: a sandboxed replay, a land worker that never runs patch code, a job model that survives a closed tab, Pocket ID sign-in, the GitHub App's device flow, and the pages for review, approval, landing and status. Python 3.14, Starlette with uvicorn, Jinja2, one vendored htmx file pinned by hash, dependencies from `uv.lock` only, no JavaScript build chain.
- The host: the Tofu VM, the DMZ interface and its rules, the Proxmox node's firewall rules, the `gatehouse` role, the Pocket ID container, and the tailnet tag, grant and tests.
- A heartbeat for the deploy job and a read-only grant to Gatus for the status panel.
- Moving the console to its own repository, with this repository pinning a release by version and sha256.

Not in this project: running Tofu or Ansible from the console, changing the rulesets or who may bypass them, and the revisions of the decisions on landing a series, workstation credentials and network reach that the ADR leaves until its assumptions are resolved.

## Decision

[ADR 0114 revision 0 (Remote series landing)](../decisions/0114-landing-a-series-from-a-device-other-than-the-laptop/revision-000.md). Its open assumptions are settled there before any stage starts.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Console seam in `land_series` | Not started | `land_series` reports progress and asks for confirmation through interfaces the CLI implements, the stop list and checks are read from the target repository's configuration, and the existing tests pass unchanged in behaviour. |
| 2 | Console core | Not started | A series replays in a transient sandbox with no network and no credentials, a separate worker verifies the output against the series hash and pushes with hooks off, and a job survives the caller disconnecting. Tests cover the approval binding, the pause conditions and token revocation. |
| 3 | Sign-in and pages | Not started | A series can be uploaded, reviewed, approved and landed in a browser against a scratch repository, after a Pocket ID login and the GitHub device flow, and the token is revoked when the series ends. The pages carry a strict content-security policy and escape all patch and review text. |
| 4 | Host | Not started | The VM is built by Tofu and configured by the role. The DMZ rules, the node's firewall rules and the tailnet tag, grant and tests are in place, and a probe from the VM to the Proxmox node's management ports fails. |
| 5 | Deploy status | Not started | The deploy job pushes a heartbeat, the console reads Gatus through one read-only grant, and the status page shows the merge commits, the checks and the heartbeat. |
| 6 | Own repository | Not started | The console is its own public repository, the role installs a release pinned by version and sha256, and this repository keeps the stop list, checks and role. |

## Acceptance criteria

- [ ] A series is uploaded, reviewed and landed from the phone over the tailnet away from home.
- [ ] No credential that can merge to `main` is on the host between series.
- [ ] A layer on the stop list pauses for the maintainer.
- [ ] The VM cannot reach the Proxmox node, the operator host or production, and the tailnet tests assert it.
- [ ] `land_series` still lands a series without the console.
- [ ] `Dependencies` of `docs/topics/deploy/gatehouse.md` states what it needs and what needs it.
- [ ] `Data` states what it stores or handles, and which of it is a secret.
- [ ] `Exposure` states what reaches it and what it reaches out to, and with which credential.
- [ ] `Threat model` states what can go wrong, what is done about it, and how that is known.
- [ ] `Observability` states how its failure is noticed and by whom.
- [ ] `Disaster recovery` states what is backed up, how it is restored, and what a rebuild still needs by hand.
- [ ] `Lifecycle` states how it is upgraded, how it is removed, and what it waits on.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter once it is set.
- **Must not change:** the replay's semantics for the CLI, the rulesets, who may bypass them, and anything that gives the console host an infrastructure credential.
- **Relevant files and interfaces:** `tools/land_series/`, [`landing-a-series.md`](../topics/engineering/landing-a-series.md), [`tailnet-policy.md`](../topics/infra/tailnet-policy.md), [`vm-provisioning.md`](../topics/infra/vm-provisioning.md), [`cd-agent-host.md`](../topics/deploy/cd-agent-host.md).
- **Required checks:** `pre-commit run --all-files`, the tests under `tools/tests/`, and a replay of a real series, as [`checks-without-docker.md`](../topics/engineering/checks-without-docker.md) describes.

A change to `tools/land_series` is applied with `git am`, not landed by the tool.

## Risks

- A change in how GitHub issues or revokes a user token, or in Pocket ID's sign-in, could force a stage to be redone.
- The DMZ interface couples landing to OPNsense being up. The CLI on the laptop is the way around it.
- The tailnet policy is edited by hand until it moves to Tofu, so the tag, grant and tests are written by hand first.

## Open items

- The VLAN and VMID, chosen from the unassigned ranges in [`vm-provisioning.md`](../topics/infra/vm-provisioning.md#vmid--vlan--ip-scheme) when stage 4 starts.
- The hostname the passkeys bind to, fixed before they are enrolled.
- Whether a name collision exists for the public repository's name.
- `allowed_paths`, derived from the stages when the project starts building.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
