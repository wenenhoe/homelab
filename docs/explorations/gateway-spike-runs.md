---
id: EXP-gateway-spike-runs
title: "How should a run against a scratch gateway be set up, started and collected so that each one starts clean?"
type: exploration
status: open
summary: "Whether the scratch gateway's rehearsals and spikes can be one command from a written spec, and whether a GitHub-hosted runner can host the gateway in place of the Proxmox node."
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

How a run is set up today ([`opnsense-scratch-gateway.md`](../topics/infra/tofu/opnsense-scratch-gateway.md), [`network-boundary-checks.md`](../topics/infra/network-boundary-checks.md#running-the-checks-against-a-scratch-gateway)):

- The gateway is a VM on the Proxmox node, on `vmbr9` with `SDN.Use` granted to the token, built by Tofu, answered at first boot over the node's serial socket and updated through its firmware API within a 30-minute bound. The operator host needs a prompt-free ssh path to the node, `OPNsense.internal` resolving to `127.0.0.1`, the pinned collection and `httpx`, and the image's URL and checksum.
- `acceptance.sh` runs the play and its checks from that setup and writes one file per step. The play's `-e` variables are written by the script there, and by hand anywhere else; the play's `opnsense_gateway_operator_not_listed_ok` has to be a real boolean, and a string `true` is not one.
- The boundary checks add six steps over three machines: a key, a plan, a copy to the node, `scratch_canaries.py up`, the runner through a `ProxyCommand`, and a teardown. A block-rule check adds a playbook with eight `-e` values. What the run printed is copied back to the person who reads it.
- The namespace tests of `scratch_canaries.py` skip on the CI runners, which run as an ordinary user.

What a GitHub-hosted runner showed when probed on 2026-11-14, on `ubuntu-26.04` (listed by GitHub as a public preview) and `ubuntu-24.04`, with the pinned image:

- `/dev/kvm` exists on both and is not openable by the runner user until a udev rule opens it. QEMU then reports KVM enabled. Intel and AMD hosts both came up, and the gateway booted on each.
- Namespaces, veth pairs, 802.1q sub-interfaces (a tagged ping crosses, mismatched tags do not), a VLAN-filtering bridge, a tap device and nft all work as root through passwordless `sudo`. The 11 tests of `scratch_canaries.py` pass as root on both images, so they would run in CI given a `sudo` step.
- The gateway, laid out as the Tofu module lays it out (WAN first on QEMU's user-mode network, LAN on a tap, the seed as a second disk, the console on a serial socket), takes the seed through the repo's own `import_seed.py` and answers its GUI and its API with the seeded key. The image download took 34 to 58 seconds (531 MB) and the unpack 42 to 69 (3.1 GB); the importer took 37 to 42.
- `update_gateway.sh` reached the update mirror through the user-mode WAN and took the gateway from 26.1.6_2 to 26.1.11_10 (79 updates, 307.5 MiB). The console shows the gateway shutting down and booting the new kernel, and the API was back about 95 seconds after the update started. The script's check that the gateway went down failed in two runs, because its poll waits up to 60 seconds for an answer and the outage lasted about 30 seconds, so a request that began inside it connected after it. With a 5-second timeout on the polls alone every check passed, in 105 seconds. A 5-second timeout on every call made the firmware status call, which contacts the mirror, fail.
- A reboot requested through `core/firmware/reboot` restarts the gateway under QEMU with the same 30-second outage.

Still to find out:

- Whether a second run finds the cached image.
- The play applied to the QEMU gateway from the runner, with the pinned collection installed from Ansible Galaxy, and the canaries reaching it over the tap bridge. Only the boot, the seed and the update have been shown.
- Whether the operator host (VM 401 now, VM 302 later) has KVM, which would give the same QEMU path without CI. The node's own nested-virtualization check in [ADR 0093](../decisions/0093-how-the-proxmox-node-is-installed-and-configured/revision-000.md) is the nearest evidence, and it is about the node.
- What a run in public CI leaves public. Logs and artifacts of a public repository are readable by anyone, so a run that goes looking for a hole would publish it before it could be fixed, against [`docs/README.md#public-repo`](../README.md#public-repo).

What no runner can show: the real `vmbr1` VLAN-aware bridge, the tailnet, the node's own firewall and the live gateway.

## Options

1. **Keep the node and wrap it.** One command takes a written spec (seed VLANs, the play's variables, the zones and canaries, the steps with the outcome each should have, what to keep) and does the setup, the steps and the teardown, then bundles the results into one file. A preflight reports each missing precondition at once. It needs no new backend and keeps what only the node can show. It still needs the node's bridge, token and ssh path, and the update's wait on the node.
2. **The same spec on a QEMU gateway on a GitHub-hosted runner.** The command is the same, and the backend is a workflow that boots the pinned image as the probe did, reuses `import_seed.py` and `update_gateway.sh`, and runs the namespaces as root. Nothing is carried between runs, and no node, bridge or token is involved. It also runs the namespace tests now skipped, and could run on a pull request that changes the flow list or the play. Cost: a second statement of the VM's layout (NIC order, disk slots, `q35`) that has to be diffed against the module so the two cannot drift, a root `sudo` step on the runner, a preview image label to pin, and the public-log limit above, which confines it to regression and rehearsal and leaves discovery runs elsewhere.
3. **The same QEMU backend on the operator host.** No CI, so a run can look for a hole in private and can use the host's credentials. Cost: it depends on KVM on that VM, which is unchecked, and it ties the operator host to a 3 GB image and a 2 GB guest.
4. **Leave the setup as it is.** A run stays as long as the person assembling it. Cost: every project in the first list pays it again, and the namespace tests stay skipped.

## Leaning

The spec and the single command come first, whichever backend runs under them, since they remove the assembly and the carrying for the node as well. The QEMU backend on a runner is the first second backend to build, for the regression and rehearsal runs the projects above end on, with discovery runs on the node or the operator host. What would change it: a play or a canary run that behaves differently on the QEMU gateway from the node's, which is the part not yet shown, or no way to keep the QEMU layout tied to the module's.
