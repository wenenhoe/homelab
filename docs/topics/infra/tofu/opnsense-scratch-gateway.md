# Scratch OPNsense gateway

A throwaway gateway for developing the [gateway play](opnsense-gateway.md) without
touching the real one, and the acceptance run that checks what the play leaves
behind. Both run from the operator host.

```sh
tofu/scratch/opnsense/scratch_gateway.sh up OUT_DIR IMAGE_URL IMAGE_CHECKSUM
tofu/scratch/opnsense/scratch_gateway.sh down OUT_DIR
tofu/scratch/opnsense/acceptance/acceptance.sh OUT_DIR IMAGE_URL IMAGE_CHECKSUM
```

## Bridges

The scratch bridges mirror the production pair: `vmbr0` is the real WAN and `vmbr1` the real VLAN-aware LAN, while `vmbr9` is the scratch gateway's VLAN-aware LAN and `vmbr8` its plain one. The scratch WAN stays on `vmbr1` with `WAN_VLAN_ID`, and `vmbr0` is refused.

## Building it

`scratch_gateway.sh up` needs `NODE`, `PROXMOX_ENDPOINT` and `PROXMOX_API_TOKEN` set.

```mermaid
flowchart TB
    a["Build seed with its own credentials<br/>OUT_DIR/credentials.tfvars"] --> b["Node stages the image<br/>stage_image.sh"]
    b --> c["Apply the OPNsense module<br/>VM stopped, VMID 501 opn-scratch"]
    c --> d["first_boot.sh"]
    d --> e["update_gateway.sh on the node<br/>to WANT_VERSION via the firmware API"]
    e --> f["ssh forward LOCAL_PORT to GUI port,<br/>print the play command"]
```

The seed uses credentials of its own, so the real credentials file is untouched. The
update is refused unless it lands on `WANT_VERSION` (default the pinned release), and
the seeded key must still authenticate, and a wrong secret still be refused,
afterwards. The root's state and provider directory live in `OUT_DIR`, and the root
uses the provider pin and lock file of the main root. `down OUT_DIR` closes the
tunnel and destroys the VM, the seed it uploaded and everything left on the node, but
not the staged image.

| Setting | Default | Notes |
| :--- | :--- | :--- |
| `LAN_BRIDGE` | `vmbr9` | Must exist with no ports and no address and be usable by the API token (`SDN.Use` on `/sdn/zones/localnetwork/<bridge>`), because the seed's LAN serves DHCP. The node takes `192.168.77.10` on it to reach the gateway. It must also be VLAN-aware (`bridge-vlan-aware yes`) for a run with a canary VM, which the run's preflight checks; `vmbr8`, a plain bridge, serves any run without one |
| `WAN_BRIDGE` | `vmbr1` | Untagged, or tagged with `WAN_VLAN_ID`, where a DHCP server gives it an address and a route out. The production WAN bridge is refused |
| `LOCAL_PORT` | 8443 | The ssh forward to the gateway's GUI port. The operator host must resolve `OPNsense.internal` to `127.0.0.1` and have no proxy variables set |
| `WANT_VERSION` | The pinned release | |
| `SEED_VLANS` | The seed's own list (20, 25, 30, 35, 40, 45, 50, 55) | Comma-separated VLAN tags the seed adds on the LAN device, such as `20,25,30,35,40,45,50,55,60`, for a zone the seed does not carry yet. The play names each zone's interface by its VLAN's position in the seed's own list, so a list should start with it, in its order: another start puts the play's rules on other VLANs. The play's `opnsense_gateway_zones` has no entry for an added tag, so its interface carries none of the play's rules |
| `PURGE_IMAGE=1` | | `down` also removes the staged image |
| `UPLOAD_IMAGE=1` | | The operator host downloads the image and the module uploads it, for a node with no route to the mirror (about 7 GB free where `OUT_DIR` is) |

### Image staging

`stage_image.sh`, piped to the node, downloads the `.img.bz2`, checks it against
`IMAGE_CHECKSUM`, unpacks it and moves it into the images datastore's `import`
directory in one rename as `<release>-nano-amd64.raw`, with the checksum beside it in
a `.sha256` file. A later run that finds the file with the checksum it asks for
fetches nothing, so the 3 GB upload through the Proxmox API, which can fail with a
closed connection, happens in no run. The checksum is checked when the image is
staged, not again when it is used.

The node needs `curl`, `bunzip2`, `pvesh` and `python3`, a route to the mirror and
about 4.5 GB free in the datastore.

## Acceptance

`acceptance.sh` runs the play against a scratch gateway it builds with
`scratch_gateway.sh` and checks what the play must leave behind:

| Check | Asserted by |
| :--- | :--- |
| A second run with `--check` exits cleanly and reports no change | `acceptance.sh` |
| A forward the play does not write, added behind its back, is reported by `--check`, removed by a run, and gone from the next `--check` | `acceptance.sh`, `stale_forward.yaml` |
| A firewall rule the play does not write, added behind its back, is reported by `--check`, removed by a run that leaves the guard rule alone, and gone from the next `--check` | `acceptance.sh`, `stray_rule.yaml` |
| The GUI login refuses the password alone, a wrong code and the code after the password, and accepts the code in front of it | `gui_login.py` |
| The API key is answered on the calls the play and the update make and refused with 403 on user management, source NAT and the service list | `api_scope.py` |
| From the node's admitted LAN address the gateway's port 443 answers and its port 22 does not; from a second address on the LAN bridge neither does | `acceptance.sh`, `management_reach.py` |
| No credential value is in the results | `acceptance.sh` |

It does not probe the flows between zones. It needs the environment of
`scratch_gateway.sh` plus `OPERATOR` (an address in the desktops zone, default
`192.168.40.250`, used as the play's operator host and one reservation), `ansible-playbook`,
the pinned collection and `httpx` on the operator host, a free `192.168.77.11` on `LAN_BRIDGE` for the probe, ssh to the node without a
prompt, and no VM with the scratch gateway's VMID. The play reaches the gateway through the ssh forward, so the run sets `opnsense_gateway_operator_not_listed_ok` and the play's check of its own source address does not apply.

`OUT_DIR` must be outside the repository because it holds the credentials file. The
results go to `OUT_DIR/run-HHMMSS` as one file per step, and the gateway is removed on
every exit path unless `KEEP=1`. The two scripts need only the standard library, and
their tests run against stand-in servers.
