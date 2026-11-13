---
id: EXP-remote-series-landing
title: "How could a series be reviewed and landed from the laptop or the phone away from home, and where would the thing that lands it run?"
type: exploration
status: open
summary: "Whether landing a series can move from a terminal on the laptop to a web console reachable over the tailnet without giving its host a standing power over `main`, and what that host, its credential and its sign-in would be."
topic: repository-tooling
related: [ADR-0112, ADR-0044, ADR-0056, ADR-0058, ADR-0053]
---

# How could a series be reviewed and landed from the laptop or the phone away from home, and where would the thing that lands it run?

A series lands today from a terminal on the laptop, under the maintainer's own `gh` login ([`landing-a-series.md`](../topics/engineering/landing-a-series.md)). That ties landing to one machine and one place. The question is whether a web console, reachable from the laptop and the phone over the tailnet, can upload a `.series` file, show it for review, replay it, push the layers and merge them, without the host that runs it holding a standing power over `main`. A merge to `main` is a deploy, so that power is close to production root. The working name for the console is Gatehouse.

## What bears on it

- [ADR 0112 (Landing a patch series)](../decisions/0112-landing-a-series-of-dependent-changes-on-main/revision-001.md) runs the tool under the maintainer's `gh` login and holds that no other credential is used. It already has a run-wide confirmation (`--yes`), a stop list of paths whose layers always ask, and a rule that the tool's own changes are not landed by it. Its replay applies each patch on a scratch worktree and runs the repository's checks, which run code from the patches. Whether a changed test outside the stop list is among what runs has to be checked.
- The CD agent fetches `main` anonymously and deploys what it finds ([`cd-agent-runner.md`](../topics/deploy/cd-agent-runner.md)). [ADR 0044 (CD agent trigger)](../decisions/0044-prod-automation-trigger-and-execution/revision-000-c.md) holds that the agent has no credential that can write to the GitHub remote, no listener that triggers or serves a job, and runs no unmerged code. The operator host is defined to hold the infrastructure credentials and to handle no untrusted content ([ADR 0058 (Operator work host)](../decisions/0058-where-operator-work-runs/revision-000.md)). The push credential is held on the laptop ([ADR 0056 (Workstation credentials)](../decisions/0056-credentials-held-by-the-maintainer-workstation/revision-000.md)). A console is exposed, parses uploaded patches and runs their checks, so it belongs on none of those hosts.
- The tailnet policy holds explicit grants only, and the Proxmox node and the subnet router are sources of nothing ([`tailnet-policy.md`](../topics/infra/tailnet-policy.md)). A new tagged node would get one grant from the maintainer's devices to its HTTPS port, no grant of its own, and a test that it reaches nothing else.
- The Proxmox node's management address sits on the upstream network that OPNsense's WAN also uses. A guest on that network is adjacent to the hypervisor's management plane, which the VLAN rules otherwise keep apart. The node is also a tailnet device, so a second path to it opens from any tailnet node the policy lets reach it.
- The VMID scheme leaves 6XX to 8XX unassigned, and a range maps to a VLAN and a /24 ([`vm-provisioning.md`](../topics/infra/vm-provisioning.md#vmid--vlan--ip-scheme)). A host on a new interface gets its own range.
- The CD agent pushes a heartbeat on success only ([`cd-agent-host.md`](../topics/deploy/cd-agent-host.md#heartbeats)). It has no listener and no write credential, so a deployed commit cannot be reported by it directly, and a console in a zone denied access to production cannot read one from the hosts.
- A GitHub App's user-to-server token acts as the user and is believed to expire after about eight hours. A passkey-only identity provider such as Pocket ID signs in with the maintainer's YubiKeys, on the phone over NFC.

Still to find out:

- Whether a ruleset's Admin bypass applies to a GitHub App's user token, and whether the merge call's `sha` parameter pins the head.
- Whether device flow works with no callback, how a user token is revoked (the revocation call is believed to need the App's client secret, which would be a standing secret on the host), and whether a refresh token can be left unrequested.
- Whether Pocket ID honours a request for a fresh login (`prompt=login` or `max_age=0`), can keep sign-up closed, and works with an NFC key in the phone's browser. A passkey is bound to the hostname, so the hostname has to be fixed first.
- Whether DMZ rules that deny every private range stop the console reaching the Proxmox node's management address, and whether the Proxmox node's own firewall can restrict 8006 and 22 to the operator path and the maintainer's tailnet devices.
- Which checks the replay runs from a patch, and whether they can run in a transient sandbox with no network and no credentials once their dependencies are fetched.

## Options

**Where it runs.**

1. **A local web UI on the laptop.** Nothing changes in ADR 0112, and nothing reaches the phone. It does not answer the question.
2. **Its own VM on a DMZ-style OPNsense interface** that allows the internet and denies every private range, reached over the tailnet. Isolation comes from rules that default to deny, egress keeps the proxy allowlist and OPNsense's logging, and the Proxmox node is blocked like any private address. It costs a new range, VLAN and interface, and it needs OPNsense up.
3. **Its own VM on the upstream-side bridge.** Isolation is structural and survives an OPNsense rebuild. It sits next to the hypervisor's management plane, so it depends on the Proxmox firewall holding, and it loses the proxy allowlist and OPNsense's view of its traffic.
4. **The CD agent host.** Rejected: it breaks all three of ADR 0044's properties above, on the host that holds the production credentials.
5. **The operator host.** Rejected: it would handle untrusted content next to the infrastructure credentials.

**What credential merges.**

1. **The laptop only,** as today.
2. **The console does everything but the Admin-bypass merge,** which the maintainer clicks in GitHub's web UI. It keeps ADR 0056 intact and gets most of the value. The UI merge cannot pin the head the maintainer reviewed.
3. **One GitHub App user token per series,** obtained by device flow, held in memory, revoked when the series completes, aborts or goes idle, and otherwise left to expire. The approval binds to the hash of the series file and each layer's tree, since a layer's commit changes when it is moved onto a new base and its tree does not. Each merge pins the head, and a failed check, a tree that differs, a stop-list layer or a timed-out wait pauses the run. It needs the verifications above and a revision of ADR 0112's credential invariant.
4. **A standing token, or an App with a standing bypass.** Rejected: it is a permanent path to production from an exposed host.

**How the console signs in.**

1. **Pocket ID on the same VM.** It suits the YubiKeys and a fresh login per series. A compromised host also controls the identity provider, which adds little exposure while a live token on that host already can merge. It adds a service and a passkey registry to the host, and the app cannot check authenticator flags to refuse synced passkeys, so only the YubiKeys are registered.
2. **Pocket ID on an internal VLAN.** Independent of the host. The console needs a path into that VLAN, and landing stops when it is down.
3. **WebAuthn in the console itself.** It can refuse backup-eligible credentials and bind an assertion to a transaction. It is more security code to own.
4. **Tailnet identity alone.** Rejected for merging: a compromised device would be enough.

**Where the source lives.**

1. **In `homelab`,** under `tools/`, with the repository's scope and decision process. The tool then lands changes to the repository it is part of, which ADR 0112 already treats as a case for `git am`.
2. **In its own public repository,** with `homelab` holding the stop list and checks as configuration, the host's role, the VM and the decisions, and pinning a release by version and sha256 the way the role pins `uv` and `rclone`. The seam the console needs, progress events and confirm callbacks in place of the terminal, is built in `homelab` first and the tool moved once it is stable.

**How the replay is contained.** It applies unmerged patches and runs their checks. Running it in a transient systemd sandbox with no network and no credentials, with dependencies fetched beforehand, keeps patch code away from the host's secrets, and a layer on the stop list would need a run with an allowlisted network and the maintainer's confirmation. Running it in the land process is simpler and gives that code the token.

**What the console shows of a deploy.**

1. **The merge, its checks and the deploy job's heartbeat,** read from Gatus through one read-only grant. It names no commit.
2. **Each host exposing its deployed commit,** which needs a read path the console's zone does not have today.
3. **A statement signed by the CD agent** that a commit was deployed. It protects the report in transit and proves nothing about the hosts, since a compromised agent can sign anything, and the agent has no way to deliver it.

## Leaning

A VM on a DMZ interface, a per-series token, Pocket ID on the VM, a sandboxed replay, the source moved to its own repository once the seam is stable, and the heartbeat for status. The leaning on credentials falls back to the second option, the maintainer's own merge in GitHub's UI, if the bypass does not apply to an App token. The placement changes if the DMZ rules cannot keep the console away from the Proxmox node, and the sign-in changes if Pocket ID cannot ask for a fresh login.
