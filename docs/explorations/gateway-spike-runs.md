---
id: EXP-gateway-spike-runs
title: "How should a run against a scratch gateway be set up, started and collected so that each one starts clean?"
type: exploration
status: open
summary: "Now that one command runs a written spec on the Proxmox node, whether a GitHub-hosted runner or the operator host should host the scratch gateway in its place."
topic: repository-tooling
related: [ADR-0089, ADR-0094]
---

# How should a run against a scratch gateway be set up, started and collected so that each one starts clean?

Several projects need to see the gateway's rules behave on a gateway that is not the live one. Each such run is assembled by hand today, and its output is carried back by hand. The question is what should assemble it, where the gateway should run, and what the run hands back, with one requirement kept fixed: every run starts from the image and the seed, and nothing is carried between runs.

## What bears on it

Who needs a gateway to run against:

- [`opnsense-config.md`](../projects/opnsense-config.md): the flow probes its exit conditions name, the stale-rule round trip (Stage 4), the seed settings and the retired allow-all rules (Stage 5), and the rehearsal before the production rebuild.
- [`network-boundary-checks.md`](../projects/network-boundary-checks.md): the runner passing every flow of the zones it reaches, and failing the flow a block rule breaks (Stage 3).
- [`coding-agent-network.md`](../projects/coding-agent-network.md) and [`coding-agent-egress.md`](../projects/coding-agent-egress.md): a seventh VLAN, the zone's rows, and the proxy's allowlist, each ending in a clean `--check --diff` and passing probes on a scratch gateway.
- [`gatehouse.md`](../projects/gatehouse.md) (a DMZ interface and a probe to the node's management ports) and the two operator-host projects, whose VLAN 30 rules are built by hand first.

How a run is set up today ([`scratch-gateway-runs.md`](../topics/infra/scratch-gateway-runs.md), [`opnsense-scratch-gateway.md`](../topics/infra/tofu/opnsense-scratch-gateway.md), [`network-boundary-checks.md`](../topics/infra/network-boundary-checks.md#running-the-checks-against-a-scratch-gateway)):

- One command, `python -m scratch_run SPEC`, takes a written spec (seed VLANs, the play's variables, the zones, the steps with the outcome each should have) and does the setup, the steps and the teardown on the Proxmox node. A preflight names every missing precondition at once, each run keeps its state in its own directory, and the results come back as one file after a scan for credentials.
- The steps are the play, the flows, a block rule, a count of the gateway's interfaces, and a canary VM cloned from a template onto a zone's VLAN. The VM needs a VLAN-aware bridge, so the gateway's LAN is `vmbr9`, VLAN-aware, and a plain `vmbr8` stands by.
- The gateway is still a VM on the node, built by Tofu, answered at first boot over the node's serial socket and updated through its firmware API within a 30-minute bound. The operator host needs a prompt-free ssh path to the node, `OPNsense.internal` resolving to `127.0.0.1`, the pinned collection and `httpx`.
- On the node, the rehearsal passed all 11 steps, the VLAN 70 seed run all 7, and the canary VM run all 6, with a tagged VM answering ssh and the zone's flows passing.
- What it does not show: the VLAN tags, which the granted API cannot read, so a count of interfaces stands in; any traffic over VLAN 70, which waits for the zone; and the firmware status, which reports a major upgrade on offer that the collection does not yet support.
- The namespace tests of `scratch_canaries.py` skip on the CI runners, which run as an ordinary user.

What a GitHub-hosted runner showed when probed on 2026-11-14, on `ubuntu-26.04` and `ubuntu-24.04`, with the pinned image:

- `/dev/kvm` exists on both and is not openable by the runner user until a udev rule opens it. QEMU then reports KVM enabled. Intel and AMD hosts both came up, and the gateway booted on each.
- Namespaces, veth pairs, 802.1q sub-interfaces (a tagged ping crosses, mismatched tags do not), a VLAN-filtering bridge, a tap device and nft all work as root through passwordless `sudo`. The 11 tests of `scratch_canaries.py` pass as root on both images, so they would run in CI given a `sudo` step.
- The gateway, laid out as the Tofu module lays it out (WAN first on QEMU's user-mode network, LAN on a tap, the seed as a second disk, the console on a serial socket), takes the seed through the repo's own `import_seed.py` and answers its GUI and its API with the seeded key. The image download took 34 to 58 seconds (531 MB) and the unpack 42 to 69 (3.1 GB); the importer took 37 to 42.
- `update_gateway.sh` reached the update mirror through the user-mode WAN and took the gateway from 26.1.6_2 to 26.1.11_10 (79 updates, 307.5 MiB). The console shows the gateway shutting down and booting the new kernel, and the API was back about 95 seconds after the update started. The script's check that the gateway went down failed in two runs, because its poll waits up to 60 seconds for an answer and the outage lasted about 30 seconds, so a request that began inside it connected after it. With a 5-second timeout on the polls alone every check passed, in 105 seconds. A 5-second timeout on every call made the firmware status call, which contacts the mirror, fail.
- The play, run from the runner with the pinned collection installed from Ansible Galaxy, applied to the QEMU gateway in 74 to 90 seconds, and a second run with `--check` reported no change. The plan, the canaries over the tap bridge and the runner's flows then ran as they do on the node: all 6 flows of the services zone and all 7 of the desktops zone passed. The block-rule round trip behaved as a stale-rule check should: the DNS flow passed, failed with the block rule applied, and passed again once it was lifted.
- The first run of the canaries on a tagged bridge stopped on a sysctl path built from a VLAN sub-interface's name. The offline tests build without VLANs and had not reached it; it is fixed and tested.
- The image is cached by its checksum: a second run restored the 3.1 GB unpacked image and skipped the download and unpack, and each run boots a throwaway overlay on it, so nothing is carried between runs. GitHub removes a cache that has not been used for 7 days, and a cache saved from one branch cannot be read from another, so a scheduled run on the default branch would keep it warm for pull requests.
- A reboot requested through `core/firmware/reboot` restarts the gateway under QEMU with the same 30-second outage.

Still to find out:

- Whether the operator host has KVM at its next incarnation (VM 302, Ubuntu 26.04 like the rest of the repo), which would give the same QEMU path without CI. The controller VM it replaces reports `/dev/kvm` and acceleration usable under `kvm-ok`, which is the nearest evidence; the node's own nested-virtualization check is in [ADR 0093](../decisions/0093-how-the-proxmox-node-is-installed-and-configured/revision-000.md).
- What a run in public CI leaves public. Logs and artifacts of a public repository are readable by anyone, so a run that goes looking for a hole would publish it before it could be fixed, against [`docs/README.md#public-repo`](../README.md#public-repo).

What no runner can show: the real `vmbr1` VLAN-aware bridge, the tailnet, the node's own firewall and the live gateway.

## Options

1. **Keep the node and wrap it.** Built. One command takes a written spec (seed VLANs, the play's variables, the zones and canaries, the steps with the outcome each should have, what to keep) and does the setup, the steps and the teardown, then bundles the results into one file. A preflight reports each missing precondition at once. It needed no new backend and keeps what only the node can show. It still needs the node's bridge, token and ssh path, and the update's wait on the node.
2. **The same spec on a QEMU gateway on a GitHub-hosted runner.** The command is the same, and the backend is a workflow that boots the pinned image as the probe did, reuses `import_seed.py` and `update_gateway.sh`, and runs the namespaces as root. Nothing is carried between runs, and no node, bridge or token is involved. It also runs the namespace tests now skipped, and could run on a pull request that changes the flow list or the play. Cost: a second statement of the VM's layout (NIC order, disk slots, `q35`) that has to be diffed against the module so the two cannot drift, a root `sudo` step on the runner, and the public-log limit above, which confines it to regression and rehearsal and leaves discovery runs elsewhere.
3. **The same QEMU backend on the operator host.** No CI, so a run can look for a hole in private and can use the host's credentials. Cost: it depends on KVM on that VM, which is unchecked, and it ties the operator host to a 3 GB image and a 2 GB guest.
4. **Leave the setup as it is.** A run stays as long as the person assembling it. Cost: every project in the first list pays it again, and the namespace tests stay skipped.

## Leaning

The spec and the single command came first, whichever backend runs under them, and are built for the node. The QEMU backend on a runner is the first second backend to build, for the regression and rehearsal runs the projects above end on, with discovery runs on the node or the operator host. What would change it: a play or a canary run that behaves differently on the QEMU gateway from the node's, which has not happened in the flows and the block-rule round trip run so far, or no way to keep the QEMU layout tied to the module's.

Leanings on how the QEMU backend would run, if it is built:

- A workflow that runs on pull requests touching what the gateway depends on (the flow list, `tools/network_checks/`, the gateway role, `tofu/scratch/opnsense/`, the seed importer), and on a weekly schedule on the default branch, which keeps the image cache from expiring and lets pull requests read it. It is not a required check at first: the run is several minutes and the runner image changes under it.
- The runner label is pinned to `ubuntu-26.04`, not `ubuntu-latest`, so the label's migration does not change what the run measures.
- It stays a regression and rehearsal run. A run that looks for a hole does not go through public CI.
