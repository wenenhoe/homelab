# Ansible Reference

Reference tables for everything under `ansible/`. For the `deploy.yaml`
play-by-play and role responsibilities during a deploy, see
[`deployment-flow.md`](deployment-flow.md).

## Playbooks

| Playbook File | Inventory | Description |
| :--- | :--- | :--- |
| `playbooks/deploy.yaml` | `inventory/inventory.yaml` | Master playbook — converges the entire infrastructure: Docker install, Caddy, BIND9, and every application. See [`deployment-flow.md`](deployment-flow.md). |
| `playbooks/cleanup.yaml` | `inventory/inventory.yaml` | Tears down stacks that are deployed/running on a host but no longer listed in its `compose_apps`, with a keep/delete policy for their on-disk content and named Docker volumes. See [`cleanup.md`](cleanup.md). |
| `playbooks/maintenance.yaml` | `inventory/inventory.yaml` | Server maintenance: `apt` upgrade + reboot-if-required, `fwupd` firmware updates + reboot-if-required. |
| `playbooks/reset-network.yaml` | `inventory/sos-inventory.yaml` | Re-applies `netplan` on every host; used when a host's network config needs a clean reset. |
| `playbooks/restore.yaml` | `inventory/inventory.yaml` | Restores one app's named volume(s) from a decrypted offsite backup archive (stage 1 DR). See [`restore.md`](restore.md). |
| `playbooks/volume-file-rm.yaml` | `inventory/inventory.yaml` | Removes specific, named file(s) from a volume that's staying deployed, without touching the rest of its content. See [`volume-maintenance.md`](volume-maintenance.md). |
| `playbooks/volume-reset.yaml` | `inventory/inventory.yaml` | Wipes a volume entirely and recreates it, restoring only Ansible-seeded content. See [`volume-maintenance.md`](volume-maintenance.md). |
| `playbooks/rotate-secret.yaml` | none — `hosts: localhost` | Deletes one generated secret's cached value, so the next `deploy.yaml` run regenerates it. Doesn't redeploy anything itself. See [`secrets-rotation.md`](secrets-rotation.md). |
| `playbooks/bootstrap-secrets.yaml` | none — `hosts: localhost` | Leading play imported by `deploy.yaml`/`restore.yaml` to resolve `secrets_registry.yaml`. See [`secrets.md`](secrets.md). |
| `playbooks/pin-telegram-topics.yaml` | none — `hosts: localhost` | Pins a static header message in each Telegram forum topic. See [`telegram-notifications.md`](telegram-notifications.md). |
| `playbooks/ci_boot_test.yaml` | `ci-inventory/` | CI-only: seeds one app for the compose boot-test job. See [`ci.md`](ci.md). |

## Roles

| Role | Purpose |
| :--- | :--- |
| `apt` | System package updates. |
| `fwupd` | Firmware updates. |
| `docker` | Docker Engine install. |
| `qemu_guest_agent` | Installs `qemu-guest-agent` for Proxmox VM integration. |
| `compose` | Reusable init/deploy/cleanup tasks for one compose app. |
| `compose_app` | Batch-drives `compose` for every non-infra app. |
| `caddy` | Renders Caddyfile, builds custom image, deploys. |
| `caddy_cert_expiry` | Alerts if Caddy's live-serving cert is expiring/unreachable. |
| `bind9` | Renders zone files, deploys, rewires host DNS. |
| `seaweedfs_bucket` | Ensures the offsite-backup S3 bucket exists on `storage`. |
| `lldap_bootstrap` | Automates lldap's `observer` account for tinyauth's LDAP bind. |
| `step_ca_client` | Shared prerequisite: caches step-ca's root cert on the host. |
| `lldap_cert` | Issues/renews lldap's LDAPS cert from step-ca. |
| `telegram_notify` | Shared library role: direct-curl Telegram alert unit. |
| `telegram_topic_pins` | Shared library role: posts/pins a static per-topic header message, control-node-only. |
| `tinyauth_ca_trust` | Builds the CA bundle tinyauth needs to trust step-ca-issued certs. |
| `tinyauth` | Molecule-only: deploys tinyauth for real in its own scenario. |
| `backup_agent` | Per-host offsite backup aggregation (stage 1 DR). |
| `cloud_sync` | Offsite replication of SeaweedFS archives to R2/B2/OCI. |
| `restore` | Restores a decrypted offsite archive back to a named volume. |
| `secrets` | Generates/validates every entry in `secrets_registry.yaml`. |
| `molecule_helpers` | Shared Molecule test fixtures/setup, not deployed. |

## Tag-based commands

- Skip the Docker Engine install on hosts that already have it:
  ```sh
  ansible-playbook playbooks/deploy.yaml --skip-tags "initial-setup"
  ```
- Pull/rebuild changed images and recreate their containers only:
  ```sh
  ansible-playbook playbooks/deploy.yaml --tags "images"
  ```
- Re-render Caddyfile/DNS zones, restarting only containers whose config
  changed:
  ```sh
  ansible-playbook playbooks/deploy.yaml --tags "infra"
  ```

Both assume the host is already provisioned once (a full, untagged run
first). See [Tags in `deployment-flow.md`](deployment-flow.md#tags).

## Inventory

Separate inventories exist for different situations:

| Inventory | Used by | Host addressing | Purpose |
| :--- | :--- | :--- | :--- |
| `inventory/inventory.yaml` | `playbooks/deploy.yaml`, `playbooks/maintenance.yaml` | `<host>.{{ ddns_domain }}` (DNS name) | Day-to-day operation once DNS is up |
| `inventory/sos-inventory.yaml` | `playbooks/reset-network.yaml` | Static IPs (see [`vm-provisioning.md`](vm-provisioning.md#vmid--vlan--ip-scheme) for the scheme) | Recovery path when DNS/network is down |

`inventory/inventory.yaml` also defines groups the roles depend on directly:

- **`app_hosts`** — every host that owns `compose_apps` / `dns_zones` / `caddy_domain`; the `bind9` role iterates this group's `hostvars` to build DNS zone files.
- **`dns`** — the host (`services`) the `bind9` role actually runs on.
