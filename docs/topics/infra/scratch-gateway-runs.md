# Scratch gateway runs from a spec

One command takes a written spec, builds a [scratch gateway](tofu/opnsense-scratch-gateway.md), runs the spec's steps in order, removes the gateway and bundles what each step printed into one archive. It replaces assembling a run by hand from `scratch_gateway.sh`, the play, `scratch_canaries.py` and the runner, and carrying their output back. Every run starts from the image and the seed, and nothing is carried from one run to the next.

```sh
cd tools
python -m scratch_run --init-env          # once: writes ~/.config/homelab/scratch-run.env, to fill in
python -m scratch_run --list              # the specs there are, and what each shows
python -m scratch_run rehearsal --check-spec   # read the spec and check it against the flow list, nothing else
python -m scratch_run rehearsal --preflight    # also check everything the run needs, then stop
python -m scratch_run rehearsal                # run it
python -m scratch_run rehearsal --backend qemu # run it on a QEMU gateway on this machine, not on the node
python -m scratch_run --ssh status             # is the ssh master to the node up? (also: up, down)
```

A spec is named by its file's stem in [`tofu/scratch/opnsense/runs/`](../../../tofu/scratch/opnsense/runs/rehearsal.yaml) or given as a path. The exit status is 0 when every step had the outcome the spec expected, 1 when one did not, and 2 when the run could not start.

## Settings

Nothing is typed per run. `--init-env` writes the settings file, `KEY=VALUE` lines read as text and never run as a shell script, and the command reads it on every run. It holds the Proxmox token, so it has to be owned by you, mode 600 and outside the repository; the command refuses it otherwise. Beside the variables `scratch_gateway.sh` takes (`NODE`, `PROXMOX_ENDPOINT`, `PROXMOX_API_TOKEN`, `VM_ID`, `LAN_BRIDGE` and the rest) and `ANSIBLE_PLAYBOOK`, it holds `SCRATCH_RUN_OUT_DIR`, `SCRATCH_RUN_IMAGE_URL` and `SCRATCH_RUN_IMAGE_CHECKSUM`. A real environment variable beats the file, and a flag (`--image-url`, `--image-checksum`, `--env-file`, or `OUT_DIR` after the spec) beats both. `OUT_DIR` holds the gateway's state and credentials and has to be outside the repository too.

## The ssh master

`scratch_gateway.sh` and the node backend talk to the node without ever being able to answer a prompt, so a master connection has to be open first, at the socket `SSH_CONTROL_PATH` names (default `~/.cache/scratch-run/ssh.sock`, in a directory only you can enter). Every ssh command of the run, and the gateway's GUI tunnel, multiplex over it. The command checks the socket (`ssh -O check`) before a run or a preflight and, when no master answers, opens one on your terminal, which is where a key passphrase, a password or a hardware-key touch is asked for. An opened master stays up for an hour after its last use, so repeated runs ask once. A socket file a dead master left behind is removed first, because a new master refuses to start beside it. `--ssh up`, `--ssh status` and `--ssh down` do the same by hand: `status` exits 1 when no master is up. Without `NODE` set, no master is touched.

## The spec

A spec is a YAML file under [`tofu/scratch/opnsense/runs/`](../../../tofu/scratch/opnsense/runs/rehearsal.yaml). The loader (`scratch_run.spec`) refuses an unknown key, a repeated step id, a tag or a flow id the [flow list](network-boundary-checks.md#the-flow-list) does not have, and a block step with no rule, and it names every problem at once, so a mistake costs no gateway build.

| Key | Meaning |
| :--- | :--- |
| `name`, `description` | The run's name, which is also its results directory, and what it shows |
| `gateway.vlans` | Optional. The seed's VLAN list, passed to `scratch_gateway.sh` as `SEED_VLANS`; unset, the seed keeps its own list |
| `gateway.play_vars` | Optional. The play's `-e` variables, each starting `opnsense_gateway_`. The three the backend sets (the CA file, the API port and the credentials file) are refused |
| `canary_vm` | Optional. `zone`: the zone whose canary a scratch VM replaces (see [the canary VM](#the-canary-vm)). A `vm` step needs it and it needs a `vm` step |
| `block_rule` | Optional. `source`, `destination`, `protocol` (`TCP` or `UDP`) and `port` of the quick block rule the block steps add and lift ([`block_rule.yaml`](../../../tofu/scratch/opnsense/boundary/block_rule.yaml)) |
| `steps` | The steps, in order |

A step has an `id` and exactly one of these:

| Step | Does | `expect` |
| :--- | :--- | :--- |
| `play: apply` or `play: check` | Runs the gateway's play, with `--check` for `check` | `ok` (exit 0, the default for `apply`), `unchanged` (exit 0 and the recap says `changed=0`, the default for `check`) or `changed` |
| `flows: {tags: [...], ids: [...]}` | Runs the [runner](network-boundary-checks.md#the-probe-module-and-the-runner) on that selection, building the namespace canaries first on the first such step | `pass` (the default) or `fail`: at least one flow the runner reports as failed, so a selection that holds no flow and a runner that crashed do not count |
| `block: present` or `block: absent` | Adds or lifts `block_rule` | None: it passes when the playbook succeeds |
| `vm: up` | Builds the canary VM and waits until it answers over ssh through the gateway; at most one, before every `flows` step (see [the canary VM](#the-canary-vm)). The VM is removed at teardown | None |
| `vlans: check` | Asks the gateway's API for its interfaces and passes when it has exactly the VLAN interfaces `gateway.vlans` seeds (below); the spec must set `gateway.vlans` | None |

The `vlans` step reads `api/firewall/filter/get_interface_list`, which the seeded API user's filter privilege covers. The privilege that would give the VLAN tags (`api/interfaces/vlan_settings/*`) is one the seed deliberately does not grant. The seed names each VLAN's interface `opt1`, `opt2`, ... in the order of its list, so a gateway seeded with six VLANs has `opt1` to `opt6`. The step shows that the seed took the spec's list (six interfaces and not five); it does not show which tag each interface carries, which the seed's own tests cover. The step's file holds the gateway's answer as it came.

A failed step does not stop the run: the later steps still run, so one archive shows everything, and the gateway is removed on every path unless `--keep` is given. The terminal shows each step as it starts, the log of each command as it prints (indented, and kept in the step's file), and for each step its time; the run ends with a table of the times and their total. Most of a run is the `up` step, which builds the gateway and updates its firmware, so its log is the one to watch.

## The canary VM

The namespace canaries stand in for every zone's canary VM. With `canary_vm: {zone: ...}` and a `vm: up` step, one zone's canary is a real VM instead: a scratch Ubuntu VM ([`tofu/scratch/ubuntu`](tofu/ubuntu-vms.md#scratch-ubuntu-vm), cloned from the template) whose VMID is the one the [VMID scheme](vm-provisioning.md#vmid--vlan--ip-scheme) gives the canary's address: 208 for the services canary at `192.168.20.8`, with the zone's VLAN tag on its NIC and the lab's static address from cloud-init. The step makes that zone's namespace skip the canary address, applies the VM, and waits (600 seconds, `VM_WAIT_SECONDS`) for the runner's ssh to reach it through the gateway as the VM's admin user. The `flows` steps after it run the zone's flows from the VM, and the runner logs in to it with `--ssh-user-for`.

The VM answers only if its NIC's tag, the bridge, the zone's rules and the address all work, so a pass shows the tagged-VM path end to end; a wrong tag is a VM that never answers. The step needs what the preflight checks:

- **A VLAN-aware bridge.** Proxmox puts a VM NIC's tag on a bridge only when the bridge is VLAN-aware. Tick VLAN aware on `LAN_BRIDGE` in the web console and apply it, or point `LAN_BRIDGE` at an isolated bridge that already is. The namespace canaries and the gateway work on either kind. The namespace canaries take a different route on an aware bridge (the veth ports get the zone's VLANs on the bridge, not a VLAN device inside the namespace), so the first run after the change should be the [rehearsal](../../../tofu/scratch/opnsense/runs/rehearsal.yaml), and [`canary-vm`](../../../tofu/scratch/opnsense/runs/canary-vm.yaml) the one after it.
- **The Ubuntu template** on the node (VM 106, or `TEMPLATE_VM_ID`) and `tofu` on this machine (`TOFU` names another).
- **No VM at the canary's VMID** left from an earlier run.

The VM's state and variables are in the run's state directory (`vm.tfstate`, `vm.tfvars.json`); a teardown whose destroy fails keeps them, and `tofu destroy` with them removes the VM by hand.

## What a run leaves

Each run builds in `OUT_DIR/state-<name>-<stamp>/`, which holds the gateway's credentials, its certificate and the runner's key. A clean teardown removes it. When the teardown fails, or with `--keep`, it stays, and `scratch_gateway.sh down` on it removes the gateway. The credentials are never in the results.

`OUT_DIR/<name>-<stamp>/` holds one `<step id>.txt` per step (plus `up.txt` and `down.txt`), `results.json` and `results.md`, and `OUT_DIR/results-<name>-<stamp>.tgz` holds the same.

`logs/` in that directory holds what the build wrote to files and not to its output, taken before the gateway is removed: `build-seed.txt`, `init.txt` and `apply.txt`, and the firmware update's files from the node, which `down` removes there (`update-job-update.log`, `update-fw-status-before.json`, `update-fw-status-after.json`, `update-config-checks.txt` and the others of its directory). Each is cut to its last 200,000 characters. The update's own output is also in `up.txt`, where its release line carries the firmware's status message beside the status word.

Before the archive is written, every file is searched for the run's credential values (the seed's root password, one-time-code seed, API key and secret, and the secret half of the Proxmox token). A file that holds one fails the run and no archive is written.

## Preflight

A run starts only when every precondition holds, and the message lists all that do not: the environment variables, the image URL and checksum in the shape `scratch_gateway.sh` requires, `OUT_DIR` outside the repository, the tools (`ssh`, `scp`, `ssh-keygen`, `ansible-playbook`, `ansible-galaxy`), `OPNsense.internal` resolving to `127.0.0.1` (with the `/etc/hosts` line to add), a prompt-free ssh path to the node, no VM at `VM_ID` and no `/root/scratch-run` left on the node from an earlier run, the pinned `oxlorg.opnsense` release and `httpx` in Ansible's Python, and a `scratch_gateway.sh` that takes `SEED_VLANS` when the spec sets `gateway.vlans`. A spec with a `canary_vm` also needs `tofu`, a VLAN-aware bridge, the Ubuntu template and a free VMID, as above.

## Backends

`scratch_run.engine` decides each step's outcome, writes the files and checks them for credentials; it does not know where the gateway runs. A backend builds the gateway, runs one step at a time and removes it (`engine.Backend`). The one that exists, `scratch_run.node.NodeBackend`, drives what a person drives today: `scratch_gateway.sh up` and `down`, the play and the block playbook from this machine through the ssh forward, and on the node `scratch_canaries.py` (its files go to `/root/scratch-run`, which `down` removes) with the runner reaching the canaries through a `ProxyCommand`. The second, `scratch_run.qemu.QemuBackend`, runs the gateway under QEMU on the machine that runs the command, so it needs no node, no Proxmox token and no ssh master. Both share the steps that do not depend on where the gateway is (`scratch_run.gateway_steps`: the play, the block rule, the API reads, the log redaction), and neither changes the spec. Choose it with `--backend qemu`; the node backend stays the default.

### The QEMU layout

A QEMU gateway has to be laid out as the Tofu module lays out the VM, or a run on it would measure another machine. `scratch_run.qemu_layout` states that layout once (`STATED`) and builds the `qemu-system-x86_64` command line from it: machine `q35`, 2 cores and 2048 MiB, one virtio-scsi controller for each disk (the module's `virtio-scsi-single`, with the system disk's iothread, discard and SSD flag), the system disk booting from `scsi0` and the seed as the second disk, a virtio NIC for the WAN on user-mode networking first and one for the LAN on a tap second, and the console on a serial socket.

It also reads the same facts from `main.tf` and `variables.tf` of [`tofu/modules/proxmox_opnsense_vm`](../../../tofu/modules/proxmox_opnsense_vm/main.tf), taking each `var.` reference from its default, and `drift` names every part on which the two differ. `test_run_qemu_layout.py` fails on any difference, and CI runs it when either side changes, so neither can move alone. Three things are not the module's on purpose: the CPU model (`host` under KVM, since a runner's CPU is not the module's `x86-64-v2-AES`), the MAC addresses (the module's come from the VM id) and the disks' files (a qcow2 overlay on the cached image, and the seed file). The reader takes only what the layout states; a module attribute outside it can change without the check noticing, and that the command line boots a gateway is shown by a run, not by the test.

### The QEMU backend

Under `--backend qemu` a run does these in order, each through one recorded command so the tests see every argument list:

1. **The image.** The pinned `.img.bz2` is downloaded, its SHA-256 compared with the pin and the file unpacked into the image cache (`SCRATCH_RUN_IMAGE_CACHE`, default `~/.cache/scratch-run/image`). A download that does not match the pin is removed and stops the run. The unpacked image is kept with the checksum it came from, so a cache for the same checksum is used as it is and one for another checksum is replaced.
2. **The seed.** `build_seed.sh` builds it with the flags `scratch_gateway.sh` gives it (the LAN address, the credentials file, the WAN DHCP hostname and the spec's VLANs), so a gateway on either backend is seeded alike.
3. **The network.** A bridge with this machine's address on it (`192.168.77.10`) and a tap on the bridge for the gateway's LAN, made with `sudo -n ip`. The gateway's LAN address is `192.168.77.1`, which `OPNsense.internal` has to resolve to here.
4. **The gateway.** A qcow2 overlay of the cached image at the module's disk size, and `qemu-system-x86_64` started in the background with the command line of [the layout](#the-qemu-layout). A QEMU that exits within seconds stops the run with what it printed.
5. **The import.** `import_seed.py` drives the serial console to import the seed; the root password reaches it on its standard input, never in its arguments.
6. **The update.** `update_gateway.sh` takes the gateway to the pinned release through its firmware API, from a credentials file that exists only while it runs, after the backend waits for the gateway to answer on its API port.

The canaries are namespaces joined to the same bridge, built as root with `sudo -n` by the first `flows` step, and the runner reaches them through the same `ProxyCommand` the node backend uses. A `canary_vm` is not built: this backend has namespaces only, and the preflight refuses a spec that has one.

The accelerator is KVM, which needs `/dev/kvm` readable and writable, unless `SCRATCH_RUN_QEMU_ACCEL=tcg` asks for software emulation, which needs no device but is about twenty times slower and gets longer importer timeouts. The preflight names every precondition at once: the tools, KVM, passwordless `sudo`, the name resolving, the bridge and tap names free, the image pin well-formed and the collection release installed. The image comes from the pin file [`tofu/scratch/opnsense/image-pin.yaml`](../../../tofu/scratch/opnsense/image-pin.yaml) unless `--image-url` and `--image-checksum` or the settings name another, because a CI runner has no settings file. A change to the pinned release is a change to that file, and CI loads it on every run of the Python tests.

Everything the backend keeps of a run is redacted of the credentials the seed carries, and the engine still fails a run whose result files hold one. On a GitHub Actions runner the backend also prints each credential in `::add-mask::` once it exists, so the log of the workflow below never shows it. `down` stops the canaries, terminates QEMU (killing it after 30 seconds), removes the tap and the bridge and removes the state directory only when all of that worked.

### The workflow

[`scratch-gateway-qemu.yml`](../../../.github/workflows/scratch-gateway-qemu.yml) runs the `rehearsal` spec on a hosted runner on `--backend qemu`. A pull request runs it when a file the gateway depends on changed (the scratch run code, the flow list and runner, `tofu/scratch/opnsense/`, the OPNsense module, the gateway role and its playbook); a weekly run on the default branch keeps the cached image from being evicted for going 7 days unused, and `workflow_dispatch` takes another committed spec that needs no node. It is not a required check: it needs a runner with `/dev/kvm`, and a hosted runner's nested virtualisation is GitHub's to change. The image is cached by the hash of the pin file, and saved even when the run fails. A run reads the cache of its own ref and then the default branch's, and never another pull request's, so the weekly run on the default branch is what lets pull requests find the image, and the first run on the default branch after a new pin downloads it again. Its logs and its results archive are public, so it runs rehearsal specs only (see [`docs/README.md`](../../README.md#public-repo)).

### Where else it could run

The backend needs only the tools, `sudo -n` and a usable `/dev/kvm`, so any host that has them can run it, privately and without the node. None is set up. The operator host's VM is built from `proxmox_ubuntu_vm`, which fixes the CPU type at `x86-64-v2-AES`, a model with no `vmx`, so it would have no `/dev/kvm` and the backend would fall back to software emulation (`SCRATCH_RUN_QEMU_ACCEL=tcg`, about twenty times slower). A run there would need the module to take a CPU type with `vmx` and the node to allow nested virtualization for that VM. The node backend already covers a run that must stay private and must show the real bridge, so this was not built.

## What it does not do

- The checks of [`acceptance.sh`](../../../tofu/scratch/opnsense/acceptance/acceptance.sh) that are not the play or the flows (a forward the play does not write, the GUI login, the API key's scope) stay in that script, and it still writes the play's variables itself.
- It builds one VM at most, the canary VM, and only for a zone the play and the flow list have. VLAN 70 has neither until [the coding agent's network](../../projects/coding-agent-network.md) reaches its Stage 2, so nothing here shows traffic over VLAN 70 (see below).
- It never touches the live gateway, and it shows nothing that the scratch gateway cannot: the real `vmbr1` bridge, the tailnet and the node's own firewall.

## Untested until VLAN 70 has a zone

The VLAN 70 scratch kit (the seed's VLAN list, the VMID range up to 7XX and `lan_bridge` in the Ubuntu module) is tested as far as the gateway having the VLAN 70 interface: the `vlan-70-seed` run. What no run shows yet, because the play has no zone for VLAN 70 and the flow list no row for it:

- a VM tagged 70 reaching the gateway, which needs the zone's interface address and a pass rule;
- the zone's flows (rows 8 and 13 of [`opnsense-config.md`](../../projects/opnsense-config.md)), and that default-deny holds in VLAN 70;
- the canary VM for that zone, which is this step with `zone` naming it.

They wait for Stage 2 of [the coding agent's network](../../projects/coding-agent-network.md). Its exit condition (the zone's flows pass on a scratch gateway) is the first run of a spec like `canary-vm` for the new zone. Until then a VM at VMID 708 on the scratch gateway would sit on an interface with no rules and could show only that it is blocked.

## Tests

The tests of `tools/tests/scratch_run/` cover the loader (every refusal, and that each committed spec loads against the committed flow list), the engine against a backend with behaviour of its own, and the node backend through a runner that records each command it is given, and the API read of the `vlans` step against a TLS server with a certificate of its own. The QEMU backend is tested the same way, through a runner whose commands leave the files the real ones would, a fake QEMU process and a fake TCP check, plus the real process, port and standard-input helpers; the pin is loaded and checked for shape. None of them starts a gateway, so a change to the commands either backend issues is shown to work only by a run: on the node for the node backend, and by the workflow above for the QEMU one.
