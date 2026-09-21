---
id: ADR-0057
revision: 0
type: adr
title: Managing the maintainer workstation from the repo
solution: Ansible configures it after a manual OS install, applied from the operator host over SSH, with a TLS remote desktop for access
summary: How the maintainer workstation's configuration becomes reproducible from the repo though it is a desktop a person uses interactively.
topic: deployment-platform
status: working
related: [ADR-0001, ADR-0054, ADR-0055, ADR-0056, ADR-0058]
---

# 0057. Managing the maintainer workstation from the repo

## Problem

The maintainer workstation's configuration is reproducible from the repo like every other host, though it is a desktop that a person uses interactively.

## Context

[ADR 0001](../0001-host-configuration-reproducible-from-repo/revision-000.md) makes Ansible the only way a host is configured. [`vm-provisioning.md`](../../vm-provisioning.md) places the 4XX desktop range, including VM 401, outside Tofu and Ansible management because of manual OS installs and GPU passthrough.

VM 401 runs Ubuntu 26.04 Desktop, whose GNOME session is Wayland-only, so there is no X11 session for a remote-display shim to attach to. The desktop ships its own RDP service, with one mode that shares the live session and one that starts a headless session at login.

The workstation runs none of the infrastructure tooling ([ADR 0056](../0056-credentials-held-by-the-maintainer-workstation/revision-000.md)); the operator host does ([ADR 0058](../0058-where-operator-work-runs/revision-000.md)).

**Threat model.** The workstation is the most exposed trusted host: it handles content produced by the untrusted coding-agent host and by the web. A configuration that cannot be reproduced cannot be audited against [ADR 0056](../0056-credentials-held-by-the-maintainer-workstation/revision-000.md)'s invariants.

## Decision

- **Scope.** Ansible configures the workstation after a manual OS install. Tofu still does not manage it. The out-of-scope statement in [`vm-provisioning.md`](../../vm-provisioning.md) narrows to installation and hardware passthrough when this is built.
- **Own inventory group.** The workstation is in none of `managed_hosts`, `app_hosts`, or `patched_hosts`, and its play is run deliberately, not by a general job.
- **Applied from the operator host over SSH,** under the same handling as [ADR 0054](../0054-managing-an-untrusted-host-from-the-cd-agent/revision-000.md): a dedicated key and account, no `fetch` or `synchronize`, facts and results treated as untrusted. The management account accepts connections only from the operator host, which the workstation cannot reach in return.
- **Remote access.** The desktop's RDP service over TLS with a per-user credential, reachable only from the maintainer's client addresses. Hypervisor console access is reserved for recovery.

## Alternatives considered

- **Stay unmanaged.** The credential audit and SSH client configuration could not be reproduced or checked. Rejected.
- **Applied locally by the maintainer's account.** Needs the infrastructure tooling on the workstation and lets the account that handles untrusted content change what the role enforces. Rejected.
- **Applied by the CD agent.** Adds a duty and an outbound path to a host designed for polling only. Rejected.
- **Rebuild-first like [ADR 0054](../0054-managing-an-untrusted-host-from-the-cd-agent/revision-000.md).** The workstation carries working state and a manual install. Rejected.

## Assumptions

- **Claim:** the desktop's RDP service on Ubuntu 26.04 gives the maintainer an authenticated TLS session from a Windows client that survives disconnects, in at least one of its two modes.
  **Breaks if wrong:** remote access falls back to the hypervisor console reached through an encrypted tunnel.
  **Checked by:** a throwaway spike on a scratch VM.

## Consequences

- The workstation's management key lives on the operator host, and the workstation cannot reach it.
- The desktop and remote-session parts of the role cannot run in a container, so its Molecule scenario covers accounts, SSH client configuration, packages, and the credential audit only.

## Invariants

- The role never places an infrastructure credential on the workstation.
- No network path leads from the workstation to the operator host.

## Non-goals

- Automating the OS install or GPU passthrough.
- Desktops other than VM 401.
- What the workstation holds ([ADR 0056](../0056-credentials-held-by-the-maintainer-workstation/revision-000.md)).

## Validation

The role's Molecule scenario and the credential audit from [ADR 0056](../0056-credentials-held-by-the-maintainer-workstation/revision-000.md).
