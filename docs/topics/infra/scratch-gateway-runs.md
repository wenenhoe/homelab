# Scratch gateway runs from a spec

One command takes a written spec, builds a [scratch gateway](tofu/opnsense-scratch-gateway.md), runs the spec's steps in order, removes the gateway and bundles what each step printed into one archive. It replaces assembling a run by hand from `scratch_gateway.sh`, the play, `scratch_canaries.py` and the runner, and carrying their output back. Every run starts from the image and the seed, and nothing is carried from one run to the next.

```sh
cd tools
python -m scratch_run ../tofu/scratch/opnsense/runs/rehearsal.yaml OUT_DIR --image-url IMAGE_URL --image-checksum IMAGE_CHECKSUM
python -m scratch_run SPEC --check-spec                                       # read the spec and check it against the flow list, nothing else
python -m scratch_run SPEC OUT_DIR --image-url ... --image-checksum ... --preflight   # also check what the run needs
```

The environment is the one `scratch_gateway.sh` takes (`NODE`, `PROXMOX_ENDPOINT`, `PROXMOX_API_TOKEN`, `VM_ID`, `LAN_BRIDGE` and the rest), plus `ANSIBLE_PLAYBOOK`. `OUT_DIR` holds the gateway's state and credentials and has to be outside the repository. The exit status is 0 when every step had the outcome the spec expected, 1 when one did not, and 2 when the run could not start.

## The spec

A spec is a YAML file under [`tofu/scratch/opnsense/runs/`](../../../tofu/scratch/opnsense/runs/rehearsal.yaml). The loader (`scratch_run.spec`) refuses an unknown key, a repeated step id, a tag or a flow id the [flow list](network-boundary-checks.md#the-flow-list) does not have, and a block step with no rule, and it names every problem at once, so a mistake costs no gateway build.

| Key | Meaning |
| :--- | :--- |
| `name`, `description` | The run's name, which is also its results directory, and what it shows |
| `gateway.vlans` | Optional. The seed's VLAN list, passed to `scratch_gateway.sh` as `SEED_VLANS`; unset, the seed keeps its own list |
| `gateway.play_vars` | Optional. The play's `-e` variables, each starting `opnsense_gateway_`. The three the backend sets (the CA file, the API port and the credentials file) are refused |
| `block_rule` | Optional. `source`, `destination`, `protocol` (`TCP` or `UDP`) and `port` of the quick block rule the block steps add and lift ([`block_rule.yaml`](../../../tofu/scratch/opnsense/boundary/block_rule.yaml)) |
| `steps` | The steps, in order |

A step has an `id` and exactly one of these:

| Step | Does | `expect` |
| :--- | :--- | :--- |
| `play: apply` or `play: check` | Runs the gateway's play, with `--check` for `check` | `ok` (exit 0, the default for `apply`), `unchanged` (exit 0 and the recap says `changed=0`, the default for `check`) or `changed` |
| `flows: {tags: [...], ids: [...]}` | Runs the [runner](network-boundary-checks.md#the-probe-module-and-the-runner) on that selection, building the namespace canaries first on the first such step | `pass` (the default) or `fail`: a failure of the flows, so a selection that holds no flow does not count |
| `block: present` or `block: absent` | Adds or lifts `block_rule` | None: it passes when the playbook succeeds |

A failed step does not stop the run: the later steps still run, so one archive shows everything, and the gateway is removed on every path unless `--keep` is given.

## What a run leaves

`OUT_DIR/<name>-<stamp>/` holds one `<step id>.txt` per step (plus `up.txt` and `down.txt`), `results.json` and `results.md`, and `OUT_DIR/results-<name>-<stamp>.tgz` holds the same. Before the archive is written, every file is searched for the run's credential values (the seed's root password, one-time-code seed, API key and secret, and the secret half of the Proxmox token). A file that holds one fails the run and no archive is written.

## Preflight

A run starts only when every precondition holds, and the message lists all that do not: the environment variables, the image URL and checksum in the shape `scratch_gateway.sh` requires, `OUT_DIR` outside the repository, the tools (`ssh`, `scp`, `ssh-keygen`, `ansible-playbook`, `ansible-galaxy`), `OPNsense.internal` resolving to `127.0.0.1` (with the `/etc/hosts` line to add), a prompt-free ssh path to the node, no VM at `VM_ID` and no `/root/scratch-run` left on the node from an earlier run, the pinned `oxlorg.opnsense` release and `httpx` in Ansible's Python, and a `scratch_gateway.sh` that takes `SEED_VLANS` when the spec sets `gateway.vlans`.

## Backends

`scratch_run.engine` decides each step's outcome, writes the files and checks them for credentials; it does not know where the gateway runs. A backend builds the gateway, runs one step at a time and removes it (`engine.Backend`). The one that exists, `scratch_run.node.NodeBackend`, drives what a person drives today: `scratch_gateway.sh up` and `down`, the play and the block playbook from this machine through the ssh forward, and on the node `scratch_canaries.py` (its files go to `/root/scratch-run`, which `down` removes) with the runner reaching the canaries through a `ProxyCommand`. A run on a QEMU gateway would be a second backend and would not change the spec.

## What it does not do

- The checks of [`acceptance.sh`](../../../tofu/scratch/opnsense/acceptance/acceptance.sh) that are not the play or the flows (a forward the play does not write, the GUI login, the API key's scope) stay in that script, and it still writes the play's variables itself.
- It never touches the live gateway, and it shows nothing that the scratch gateway cannot: the real `vmbr1` bridge, the tailnet and the node's own firewall.

## Tests

The tests of `tools/tests/scratch_run/` cover the loader (every refusal, and that each committed spec loads against the committed flow list), the engine against a backend with behaviour of its own, and the node backend through a runner that records each command it is given. None of them starts a gateway, so a change to the commands the node backend issues is shown to work only by a run on the node.
