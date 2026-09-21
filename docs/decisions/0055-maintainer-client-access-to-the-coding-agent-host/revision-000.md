---
id: ADR-0055
revision: 0
type: adr
title: Maintainer client access to the coding-agent host
solution: One workstation identity, terminal-only SSH to the host on a dedicated key, and review by git fetch and a local diff
summary: How the maintainer drives the agent and reviews its work without the host gaining a path to the workstation's push credential.
topic: security-hardening
status: working
related: [ADR-0050, ADR-0053, ADR-0056, ADR-0057]
---

# 0055. Maintainer client access to the coding-agent host

## Problem

The maintainer drives the agent and reviews its work from the workstation. The untrusted host must not gain a path into the credential that workstation holds.

## Context

The workstation (VM 401 today, per [`tofu-vm-provisioning.md`](../../projects/tofu-vm-provisioning.md)) holds the push credential ([ADR 0050](../0050-agent-authored-changes-reaching-production/revision-000.md)) and, under [ADR 0056](../0056-credentials-held-by-the-maintainer-workstation/revision-000.md), no infrastructure credential.

The firewall rule "the host may not initiate to the workstation" ([ADR 0053](../0053-network-reach-of-the-coding-agent-host/revision-000.md)) does not cover the connection the workstation itself opens. A remote-editor session runs a server-side component on the host and renders what it returns on the client; SSH agent, port, and X11 forwarding are further client-side surfaces. Content the host produces can also be run by the maintainer later: git hooks, pre-commit configuration, editor task files, playbooks.

**Threat model.** The adversary controls the host. The asset is the push credential. The attack path is the maintainer's own client connection and the content they open from the host.

## Decision

- **Driving** is a plain SSH terminal session to the host, authenticated by one key used for nothing else. The client configuration for that host disables agent, X11, and port forwarding. No remote-editor session runs against the host.
- **Review** is by git. The host's repository is a remote on the workstation; the maintainer fetches it and reads the diff in a local clone before checking anything out where it executes (hooks, pre-commit, Ansible, Molecule, editor tasks), with the editor's workspace trust restricted until then. Pushing follows [ADR 0050](../0050-agent-authored-changes-reaching-production/revision-000.md).

## Alternatives considered

- **Remote-editor sessions.** Convenient, but they run a component from the untrusted host inside the maintainer's workflow. Rejected.
- **A separate account or profile for driving.** Costs a second identity to maintain, for a workstation that holds only the push credential once [ADR 0056](../0056-credentials-held-by-the-maintainer-workstation/revision-000.md) lands. Rejected.
- **A fetch-only key restricted on the host.** Limits what the key can do on a host that is untrusted anyway; the host can answer any request regardless. Rejected.
- **A separate client VM.** The step up if the residual risk below becomes unacceptable.

## Consequences

- The terminal, SSH client, and git are the client-side surface a compromised host can attack, and they run in the account holding the push credential. This residual risk is accepted.
- Edits reach the host through the agent or as patches, not through the workstation's editor.

## Invariants

- The key used for the host authenticates to nothing else.
- No remote-editor session runs against the host.
- Nothing fetched from the host executes before its diff is read.

## Non-goals

- What the host may reach ([ADR 0053](../0053-network-reach-of-the-coding-agent-host/revision-000.md)).
- Who holds the push credential ([ADR 0050](../0050-agent-authored-changes-reaching-production/revision-000.md)).

## Validation

A check of the client configuration confirms the host's entry disables forwarding and names the dedicated key, and that no other host's entry uses that key.
