# OpenTofu-Driven Proxmox VM Provisioning

**Status:** `In progress`

Builds the OpenTofu code implementing the design already recorded in
[`docs/vm-provisioning.md`](../vm-provisioning.md) — VMID/VLAN/IP/MAC
scheme, Ubuntu/OPNsense provisioning, and the Tofu↔Ansible boundary —
through the migration cutover that design describes.

## Environment (baseline, at project start)

Live `pve` node: 6-core i5-9400, 32GB RAM, NVMe boot SSD (`local` +
`local-lvm`, 1TB) plus a secondary HDD (`backup`, 1TB). This is the
actual `qm list` the VMID scheme in `vm-provisioning.md` was checked
against:

| VMID | Name | Status | Notes |
| :-: | :--- | :--- | :--- |
| 103 | Win10ProKMS | stopped | Template; standalone KMS-activated |
| 104 | Win11Pro | stopped | Template; uses KMS on `services` |
| 105 | Win11ProGPU | stopped | Template |
| 201 | OPNsense | running | Gateway |
| 202 | Tailscale | stopped | Subnet router, `192.168.20.0/24` |
| 203 | Services | running | Ansible-managed |
| 204 | Play | running | Ansible-managed (Minecraft) |
| 205 | Security | running | Ansible-managed |
| 206 | Storage | running | Ansible-managed; SeaweedFS S3 |
| 401 | Development | running | Runs this project's tooling (Tofu/Ansible) |
| 402 | ZorinPC | stopped | Desktop |
| 403 | Personal | running | GPU passthrough |

VMIDs 103–105/401–403 aren't in any Ansible inventory and are out of
this project's scope. `local` has 37GB free, `local-lvm` 523GB,
`backup` 693GB — noted here since it's what informed the "no storage
placement changes needed" call for the ISO/template content type.

This table is a snapshot, not a tracked value — it will drift once
Stage 5 starts moving real VMs; don't treat it as current after that.

## Stages

| # | Stage | Status |
| :-: | :--- | :--- |
| 1 | Tofu project skeleton — provider, state backend, secrets bootstrap | Not started |
| 2 | `proxmox_ubuntu_vm` module | Not started |
| 3 | `proxmox_opnsense_vm` module — Phase 1 (VM shell + ISO fetch) | Not started |
| 4 | Tofu→Ansible inventory generator | Not started |
| 5 | Migration Stage 1 + 1.5 — build the 5XX block, first `restore.yaml` run | Not started |
| 6 | Migration Stage 2 — cutover to real VMID ranges, decommission old VMs | Not started |
| 7 | OPNsense Phase 2 — API-driven day-2 config (Kea, VLAN, static DNS) | Not started |

"Migration Stage" in rows 5–6 is `vm-provisioning.md`'s own numbering
for its cutover plan, not this table's row numbers — the two are
independent sequences that happen to share a word; see
[`docs/projects/README.md`](README.md#stage-track-phase--scoped-per-doc).

## Stage detail

### Stage 1 — Tofu project skeleton

- `bpg/proxmox` provider, API token auth against the `pve` node.
- State backend: S3-compatible, pointed at SeaweedFS on `storage`
  (`s3.store.lan.<main_domain>`, `:8333` internally — see
  `docker/seaweedfs/compose.yaml.j2`). Bucket name: `opentofu-state`,
  matching the `<component>-<purpose>` pattern `openbao-snapshots`
  already uses (`homelab-backups` is the one exception, since it's
  shared across every host rather than owned by one component).
  SeaweedFS doesn't auto-create buckets
  (`ansible/roles/seaweedfs_bucket`) — creating this one is a one-time
  manual step, not yet Ansible-managed.
- Tofu's own secrets (Proxmox API token, OPNsense API key,
  state-backend S3 credential):
  a real open decision between three options — see the
  [decision draft](../decisions/drafts/tofu-secrets-and-state-backend-location.md).
  This stage is blocked on it.
- Install: OpenTofu's official apt-repo installer, on VM 401
  ("Development") once it exists, otherwise wherever the repo's
  driven from today. `bpg/proxmox` needs no separate install — fetched
  by `tofu init`, the same way `ansible-galaxy collection install`
  fetches Ansible's collections.

### Stage 3 — OPNsense Phase 1

VM shell + ISO fetch only, per `vm-provisioning.md`'s OPNsense
section — install and initial config stay manual. Phase 2 (Stage 7)
is where day-2 config becomes API-driven.

### Stage 5 — Migration Stage 1 + 1.5

The current 2XX hosts are live and can't be edited in place, and
resources on `pve` are tight enough that downsizing during the move is
part of the plan — migration happens in stages rather than a single
cutover.

**Migration Stage 1** — Tofu provisions a new OPNsense + one Ubuntu VM
on the `5XX` block (VLAN 50), fully isolated from production. Its WAN
NIC plugs into the same VLAN-aware trunk bridge as everything else,
tagged into VLAN 20 — an ordinary DHCP client of the *current*
OPNsense's LAN, not the physical WAN bridge. This lets it reach
`storage` (still live, same VLAN) and the internet (NATed through the
current OPNsense) with zero firewall/routing changes on production.

**Migration Stage 1.5** — first real run of `restore.yaml` against the
Stage 1 VM(s): validates disaster recovery and rehearses the actual
cutover mechanics at the same time. See
[`fire-drill.md`](../fire-drill.md) for how this doubles as the
restore-path fire drill once OpenTofu is up.

### Stage 6 — Migration Stage 2

Once Migration Stage 1.5 is proven, rebuild on the real VMID ranges
(1XX/2XX/...), cut over, decommission the old VMs. `storage` stays up
throughout every stage — it holds both the Tofu state backend and the
DR restore target.

### Stage 7 — OPNsense Phase 2

Depends on the VMID→IP mapping being fully code-driven (Stages 1–6).
Static host overrides for Tofu-provisioned VMs go through OPNsense's
own config API against its BIND plugin's normal record model — not
raw zone-file editing, which the plugin doesn't support (verified
against the plugin's own issue tracker, not assumed). Whether this
stays the design, or Tofu-sourced A records move to a dedicated
internal nameserver instead, is a real open decision — captured as a
decision draft once written. This stage is blocked on it too.

## Open items

- Tofu-only secrets and state-backend credential location (Stage 1) —
  [decision draft](../decisions/drafts/tofu-secrets-and-state-backend-location.md).
- Internal DNS for Tofu-provisioned VMs (Stage 7) — decision draft
  pending.
- Migration Stage 2's exact rebuild sequence isn't scoped beyond
  "rebuild on real VMID ranges, cut over, decommission" — needs its
  own detail once Stage 5 is proven.

## Closing checklist

Copied from
[`docs/projects/README.md`](README.md#when-a-project-finishes) — run
before deleting this doc once every stage above is Done.

- [ ] Every `Done` stage's rationale exists as a real ADR, or plainly
      didn't need one.
- [ ] Every `Done` stage's current behavior is described in
      `docs/vm-provisioning.md` or a new topic doc, not only here.
- [ ] Every open item above is resolved-and-promoted or moved to
      where it belongs next.
- [ ] Every cross-reference into this doc elsewhere in the repo is
      updated or removed.
