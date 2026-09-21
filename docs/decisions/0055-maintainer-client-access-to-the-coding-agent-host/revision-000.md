---
id: ADR-0055
revision: 0
type: adr
title: Maintainer client access to the coding-agent host
solution: Two client identities on the workstation, one low-privilege for driving the agent and one that only fetches
summary: How the maintainer drives and reviews agent work without the host gaining a path to the workstation's push credential and infrastructure keys.
topic: security-hardening
status: working
related: [ADR-0050, ADR-0053]
---

# 0055. Maintainer client access to the coding-agent host

## Problem

The maintainer drives the agent and reviews its work from the workstation. The untrusted host must not gain a path into the credentials that workstation holds.

## Context

The workstation (VM 401 today, per [`tofu-vm-provisioning.md`](../../projects/tofu-vm-provisioning.md)) runs the repo's Tofu and Ansible tooling and holds the shared infrastructure SSH key. Under [ADR 0050](../0050-agent-authored-changes-reaching-production/revision-000.md) it also holds the only push credential.

The firewall rule "the host may not initiate to the workstation" ([ADR 0053](../0053-network-reach-of-the-coding-agent-host/revision-000.md)) does not cover the connection the workstation itself opens. A remote editor session runs a server-side component on the host and renders what it returns on the client; SSH agent, port, and X11 forwarding are further client-side surfaces. Content the host produces can also be run by the maintainer later: git hooks, pre-commit configuration, editor task files, playbooks.

**Threat model.** The adversary controls the host. The asset is the credential-holding workstation session. The attack path is the maintainer's own client connection and the content they open from the host.

## Decision

The workstation runs two separate identities.

- **Driving identity.** A low-privilege OS account or profile holding one SSH key, dedicated to the coding-agent host, and nothing else: none of the infrastructure keys, no push credential, no access to the privileged account's home. Its SSH configuration disables agent, X11, and port forwarding. Its editor uses a separate profile with workspace trust on. Interactive sessions, including remote-editor sessions, run only here.
- **Fetching identity.** The privileged maintainer account never opens an interactive session to the host. It fetches from the host's repository ([ADR 0050](../0050-agent-authored-changes-reaching-production/revision-000.md)) with a key limited on the host, in an authorized-keys entry the agent account cannot edit, to serving git fetches for that one repository.

Fetched work is reviewed as a diff before it is checked out anywhere that executes it.

## Alternatives considered

- **One account with a hardened SSH configuration.** The same home directory holds the infrastructure keys. Rejected.
- **Terminal-only access with no remote editor.** Removes the editor's client-side surface entirely. The fallback if the remote editor cannot be contained.
- **A separate client VM.** Stronger than an OS account, at the cost of another host to run. The step up if OS-account separation is judged insufficient.

## Assumptions

- **Claim:** separation by OS account on the workstation is a sufficient boundary between agent-facing sessions and the credential-holding account.
  **Breaks if wrong:** a compromised driving session reaches the privileged account through a shared desktop session, clipboard, or kernel, and the driving identity moves to a separate VM.
  **Checked by:** reading how the workstation's desktop session is used, then a review of what the two accounts can reach.
- **Claim:** a root-owned authorized-keys entry with a forced command can serve `git fetch` for a repository owned by the agent account, given git's repository-ownership check.
  **Breaks if wrong:** fetching needs a shell-capable key, and the fetching identity falls back to the driving identity's access.
  **Checked by:** a spike on a scratch VM.

## Consequences

- Two SSH identities and two profiles to maintain on the workstation.
- Reading agent work happens through the diff, not by opening the host's workspace in the privileged account.

## Invariants

- No credential that can write to GitHub or authenticate to an infrastructure host is readable by the driving identity.
- The privileged account never runs an interactive session on the coding-agent host.

## Non-goals

- What the host may reach ([ADR 0053](../0053-network-reach-of-the-coding-agent-host/revision-000.md)).
- Who holds the push credential ([ADR 0050](../0050-agent-authored-changes-reaching-production/revision-000.md)).

## Validation

A check from the driving identity confirms it cannot read the infrastructure keys or push credential. A check on the host confirms the fetching key cannot open a shell.
