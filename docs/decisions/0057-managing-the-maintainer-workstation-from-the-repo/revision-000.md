---
id: ADR-0057
revision: 0
type: adr
title: Managing the maintainer workstation from the repo
solution: Ansible configures it after a manual OS install, applied locally by the operator tier, with per-user headless desktop sessions for remote access
summary: How the maintainer workstation's configuration becomes reproducible from the repo though it is a desktop that runs the tooling applying configuration.
topic: deployment-platform
status: working
related: [ADR-0001, ADR-0055, ADR-0056]
---

# 0057. Managing the maintainer workstation from the repo

## Problem

The maintainer workstation's configuration is reproducible from the repo like every other host, though it is a desktop that runs the tooling that applies configuration and that a person uses interactively.

## Context

[ADR 0001](../0001-host-configuration-reproducible-from-repo/revision-000.md) makes Ansible the only way a host is configured. [`vm-provisioning.md`](../../vm-provisioning.md) places the 4XX desktop range, including VM 401, outside Tofu and Ansible management because of manual OS installs and GPU passthrough.

VM 401 runs Ubuntu 26.04 Desktop, whose GNOME session is Wayland-only, so there is no X11 session for a remote-display shim to attach to. The identity tiers in [ADR 0056](../0056-credentials-held-by-the-maintainer-workstation/revision-000.md) need a separate desktop session each. A single shared console shows one session at a time.

The inventory's `controller` group is `localhost` with a local connection. The CD agent's self-run guard ([ADR 0044](../0044-prod-automation-trigger-and-execution/revision-000-a.md)) addresses self-provisioning over SSH loopback, which this host does not need.

**Threat model.** The workstation is the most exposed trusted host: it handles content produced by the untrusted coding-agent host and by the web. A configuration that cannot be reproduced cannot be audited against [ADR 0056](../0056-credentials-held-by-the-maintainer-workstation/revision-000.md)'s invariants.

## Decision

- **Scope.** Ansible configures the workstation after a manual OS install. Tofu still does not manage it. The out-of-scope statement in [`vm-provisioning.md`](../../vm-provisioning.md) narrows to installation and hardware passthrough when this is built.
- **Own inventory group.** The workstation is in none of `managed_hosts`, `app_hosts`, or `patched_hosts`, and its play is run deliberately, not by a general job.
- **Applied locally.** The operator tier runs the play against the machine itself over a local connection. No SSH management path from the CD agent, or from any other host, leads into the workstation.
- **Remote access.** Routine remote access uses per-user headless desktop sessions over TLS with per-user credentials, provided by the desktop environment's own remote-login service, reachable only from the maintainer's client addresses. Hypervisor console access is reserved for recovery.

## Alternatives considered

- **Stay unmanaged.** The tier split and credential audit could not be reproduced or checked. Rejected.
- **Applied by the CD agent over SSH.** Adds a management path from a host holding production credentials into the machine holding the push credential. Rejected while a local run suffices.
- **Rebuild-first like [ADR 0054](../0054-managing-an-untrusted-host-from-the-cd-agent/revision-000.md).** The workstation carries working state and a manual install. Rejected.
- **A shared console with fast user switching.** One visible session at a time, with the others running behind it. Kept as the fallback if per-user remote sessions do not work.

## Assumptions

- **Claim:** the desktop's remote-login service on Ubuntu 26.04 serves two users simultaneously over TLS, and the maintainer's client supports it.
  **Breaks if wrong:** remote access falls back to a shared console, and the tiers cannot be used side by side.
  **Checked by:** a throwaway spike on a scratch VM.
- **Claim:** the role can converge against the machine it runs on, repeatedly, without ending the operator's session or locking out remote access.
  **Breaks if wrong:** the play needs a second host to run from, or must exclude session-affecting settings.
  **Checked by:** the same spike, then the role's idempotence run.

## Consequences

- The workstation runs its own configuration, so a compromised operator session can change what the role enforces. The role makes the intended state reproducible and auditable; it does not stop the operator tier from being wrong.
- The desktop and remote-session parts of the role cannot run in a container, so the Molecule scenario covers accounts, SSH configuration, and the credential audit only.

## Invariants

- The role never places an infrastructure credential in a non-operator tier.
- No management path from another host leads into the workstation.

## Non-goals

- Automating the OS install or GPU passthrough.
- Desktops other than VM 401.
- What each tier holds ([ADR 0056](../0056-credentials-held-by-the-maintainer-workstation/revision-000.md)).

## Validation

The role's Molecule scenario and the tier audit from [ADR 0056](../0056-credentials-held-by-the-maintainer-workstation/revision-000.md).
