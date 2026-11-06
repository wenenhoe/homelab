# OPNsense gateway play

The Ansible play that writes the gateway's configuration through its API, after the
[VM](opnsense-vm.md) has first-booted from its seed. The gateway is not an Ansible
host: every call is to its API at `OPNsense.internal`, from the operator host.

```sh
ansible-playbook playbooks/opnsense.yaml --check --diff -e opnsense_gateway_ca_file=PATH
```

`PATH` is the `gateway-cert.pem` the [first-boot script](opnsense-vm.md#first-boot)
wrote: the only CA the play trusts. The operator host must resolve
`OPNsense.internal`. The play is `playbooks/opnsense.yaml` with the
`opnsense_gateway` role ([`ansible.md`](../../deploy/ansible.md)).

## Variables the play needs

| Variable | Why |
| :--- | :--- |
| `opnsense_gateway_ca_file` | The certificate to pin |
| `opnsense_gateway_operator_hosts=[...]` | The IPv4 addresses the work runs from. The play stops without it, since an empty guard rule would admit nobody |
| `opnsense_gateway_forward_domains=[...]` | The host zone and the lan zone, which derive from the main domain. The play stops without them |
| `opnsense_gateway_cd_agent_management` | The CD agent's rule is written only when this is true, and removed when it is false |

## Pre-checks

Before anything else the role checks:

1. The credentials file (mode `0600`, holding `opnsense_api_key` and
   `opnsense_api_secret`).
2. That the installed `oxlorg.opnsense` collection is the pinned release.
3. That `OPNsense.internal` resolves.
4. That the seeded key authenticates over the pinned certificate. A renewed GUI
   certificate fails this until the console is read again.
5. That the gateway runs the pinned release. The check asks the gateway for its
   firmware status, which probes the OPNsense mirror, so the gateway needs its route
   out.

The release and the collection's commit are the role's defaults;
`ansible/requirements.yml` installs the collection from git at the same commit, and
a test fails when the two differ.

## What it writes

| Object | Content |
| :--- | :--- |
| Aliases | One per zone's network; one for the operator hosts, the CD agent and the gateway's management ports |
| Guard rule | A floating quick pass at sequence 1 admitting the operator hosts to the gateway's SSH and API ports |
| Per-zone rules | DNS, NTP and ping to the gateway |
| Flows | The flows between zones in `opnsense_gateway_flows`: a pass rule on the source zone's interfaces, each matched by its name. One marked `enabled: false` is written but not in force |
| Internet zones | A zone marked `internet: true` also gets a rule denying direct DNS (ports 53 and 853) to anything but the gateway, and one passing its traffic to everything outside the private ranges. Other zones reach only the flows listed |
| NAT | Outbound NAT is left in the automatic mode the seed sets |
| Kea | On for zones marked `dhcp: true` (desktops and the two experimental blocks, whose clients Tofu does not place), each with a scope of `192.168.<vlan>.10` to `.245`. Keeps the reservations in `opnsense_gateway_dhcp_reservations` (`name`, `zone`, `address`, `mac`), which must sit in a Kea zone outside the pool. A zone not marked is left alone |
| Unbound | Forwards the host zone and the lan zone to the two DNS servers (`opnsense_gateway_forward_servers`, `192.168.20.3` and `192.168.20.6`). Removes any forward it does not write, which `--check` reports as a change |
