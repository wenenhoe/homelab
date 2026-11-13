# Operating modes

The lab is in one of four modes, set by two things: whether the server is up and whether the maintainer can reach it. This page says what runs in each mode, which clocks keep running while the server is off, and what is checked on the way in and the way out. It holds no dates: a planned stretch in a mode is scheduled outside the repo.

## The four modes

| Mode | Server | Maintainer | What it means |
| :--- | :--- | :--- | :--- |
| Normal | Up | Around | Deploys, maintenance, credential rotation and Tofu are run by hand |
| Away | Up | Away | Remote access is the way in, nothing is deployed, and an alert has to reach a phone |
| Dark | Down or moved | Around or away | Nothing runs on the node, the cloud copies are the only live data, and work happens off the node |
| Dark+Away | Down | Away | Dark with no quick reply: bringing the node back needs someone who can power it on and unseal OpenBao |

## What the node carries

Every VM is on the one Proxmox node: the gateway ([`opnsense-vm.md`](../infra/tofu/opnsense-vm.md)), the Tailscale subnet router ([`network-infra.md`](../infra/network-infra.md)), the controller ([`vm-provisioning.md`](../infra/vm-provisioning.md)), every app host, and the monitoring and alerting. Dark therefore takes the LAN gateway, the route into the LAN from the tailnet, the tooling that rotates credentials and applies Tofu, and every alert with it. Away keeps all of them.

## What runs, by mode

| Thing | Normal | Away | Dark |
| :--- | :--- | :--- | :--- |
| Per-app backups and cloud sync | Run | Run | No new archives |
| Certificate renewal and expiry checks | Run | Run | Nothing runs, so certificates age |
| Security updates | Run, no automatic reboot | Run, no automatic reboot | Nothing runs |
| Alerts ([Beszel](../monitoring/beszel.md), [Gatus](../monitoring/gatus.md), Telegram) | Run | Run | Do not run |
| Renovate pull requests, image builds, scans | Run | Run | Run: they are GitHub-side |
| Deploys, `maintenance.yaml`, credential rotation, Tofu | By hand | Not done | Not done |
| Provider-side clocks: lock windows, lifecycle rules, credential lifetimes | Tick | Tick | Tick |

The credential freshness check runs from a user timer on `controller` ([`expiry.md`](../secrets/cloud-credentials/expiry.md#scheduling)); it runs only while that machine is on.

## Clocks that keep running

These keep their own time while the node is off, so each is checked or set before a long stretch in Dark and checked again on the way out.

| Clock | Where it is set and described |
| :--- | :--- |
| On-site backup retention | `backup_defaults.retention_days` in the inventory, and [`backup.md`](backup.md) |
| Cloud copy lifetimes and lock windows | [`cloud-sync.md`](cloud-sync.md) |
| Cloud credential lifetimes and warnings | [`expiry.md`](../secrets/cloud-credentials/expiry.md) |
| Internal certificate lifetimes and renewal | [`gatus.md`](../monitoring/gatus.md) |
| OpenBao seals on every restart | [ADR 0018](../../decisions/0018-unsealing-the-secrets-store-after-restart/revision-000.md) |

## Before entering Away or Dark

- Nothing that changes how deploys, secrets or the network work goes live in the days before: the work is merged and deployed, or left on the scratch block at a stage boundary, never half-applied in production.
- No decision is approved that changes one of the clocks listed above.
- Every open patch is merged or discarded.

## Entering and leaving

### Normal to Away

1. From `tools/`, run `python3 -m cloud_credentials.check_credential_expiry` and rotate what is close to expiry with `python3 -m cloud_credentials.rotate_leaf_keys` ([`rotation.md`](../secrets/cloud-credentials/rotation.md)), deploy to `storage` and `localhost`, then start `cloud-sync.service` on `storage` and read its status.
2. Run `ansible/scripts/restore_all.py --check` for every host.
3. Check the alert path: Telegram posts to the Backups, Certs and Monitoring topics, the Gatus heartbeats for backups and cloud sync exist and are green, and a phone reaches Tailscale and Telegram.
4. Copy the Tofu state off the operator host and leave no building project half-applied.
5. Repeat steps 1 and 2 the day before leaving.

### Away to Normal

1. Read the alerts since leaving and Gatus's history for the backup and cloud-sync heartbeats.
2. Confirm the last cloud sync exited 0 and each cloud holds an archive for each night.
3. If a kernel update is pending, reboot `security` by hand and unseal OpenBao, then run `maintenance.yaml` limited to the patched hosts.
4. Merge and deploy the queued Renovate pull requests in small steps.

### Normal to Dark

1. Everything in Normal to Away.
2. Take a final backup on every host and on the relay, then run cloud sync once more.
3. Copy the SeaweedFS bucket and any archive that has no cloud copy off the node, to another disk or machine.
4. Set the backup retention for the stretch, and decide whether the backup agents start on boot.
5. Rotate credentials in the last days, so that each has most of its lifetime left on return.
6. Set the OCI lifecycle rule for the stretch by hand in its console.
7. Shut the VMs down in the reverse of their start order, then the node.

### Dark to Normal

1. Start the gateway first, then `security` and unseal OpenBao ([`openbao.md`](../secrets/openbao.md#init-and-unseal--manual-via-initpy-and-unsealpy)), then `storage`, then the app hosts.
2. Check the host clocks before judging any certificate.
3. Before the first backup, run `restore_all.py --check` per host and confirm the retention and the backup agents are as set.
4. Check the internal certificates, run cloud sync once and read its exit status, restore the OCI rule and the retention.
5. Run the credential expiry check and rotate what is close to expiry.
6. Record the shutdown as a cold-start exercise ([`exercises.md`](exercises.md)).
7. Deploy what queued, in small steps.

## Work that fits each mode

- **Normal:** anything.
- **Away:** work that needs no live change: code, tests, docs, explorations and project files, and sessions that run in the sandbox. Scratch VMs only while someone is at the keyboard, torn down after.
- **Dark:** the same, plus cloud-side work that does not need the node. Nothing that needs `controller`, OpenBao, Tofu or Ansible against the node.
