# Fire Drill: Proving the Restore Path Actually Works

For the backup design this proves — threat model, encryption, what's
covered — see [`disaster-recovery.md`](disaster-recovery.md). For the
per-app and batch restore runbooks themselves, see
[`restore.md`](restore.md).

Two levels of "does this actually work," proving different things:

- **`ansible/roles/restore_discovery/molecule/{default,discovery_and_restore}`** —
  automated, runs in CI/dev like any other Molecule scenario, and
  currently passing with 100% task coverage on both. `default` renders
  the manifest/rclone.conf against synthetic fixtures and asserts on
  their content (scope derivation, step-ca ordering, cloud-target
  fan-out). `discovery_and_restore` runs the real role against a real
  throwaway SeaweedFS target and a real freshly-generated GPG keypair,
  proving `restore_all.py`'s own discovery logic — newest-object-by-
  timestamp selection, and falling over to a cloud target when
  SeaweedFS is unreachable — against genuine S3 responses and a
  genuine decrypt, not mocked. Neither touches a real app host or the
  real offline private key.
- **A real fire drill** — the only thing that proves the *whole* path
  end to end: a real backup, the real offline GPG key, and a
  scratch/test host, run by hand. **Don't run `restore_all.py`'s full
  orchestration for this** — its manifest always resolves each app's
  *real* host straight from `app_registry`/`host_vars`, so it has no
  way to target a scratch host instead, and `restore.yaml` is
  destructive by design (stops the app, unconditionally overwrites the
  live volume, no dry-run). Pointed at real inventory, a drill would be
  a real, irreversible production restore. Split it into a read-only
  half and a contained half instead:
  1. Render the real manifest/rclone.conf (read-only, `hosts:
     controller` only — can't reach a real app host at all):
     ```sh
     cd ansible
     ansible-playbook playbooks/bootstrap-secrets.yaml \
       playbooks/restore-discovery-setup.yaml \
       -i inventory/inventory.yaml --limit localhost
     ```
  2. Discover and decrypt one real app's latest backup directly — still
     read-only (list + `gpg --decrypt` only), still nothing remote.
     Pick a simple app for a first drill (`wastebin`: single volume,
     not stopped during backup):
     ```sh
     python3 -c "
     import sys; sys.path.insert(0, 'ansible')
     import restore_all
     bucket, entries = restore_all.load_manifest()
     entry = next(e for e in entries if e.app == 'wastebin')
     result = restore_all.discover_and_decrypt(entry, bucket)
     print(result.source, result.object_name, result.backup_timestamp)
     print('decrypted at:', result.decrypted_path)
     "
     ```
  3. Stand up a scratch host. Two tiers, both legitimate:
     - **Now**, before OpenTofu exists: any isolated segment/host you
       can already stand up — doesn't need to be VLAN 50, just isolated
       enough that nothing depends on it. Waiting for Tofu before
       running this once doesn't reduce the risk it's meant to catch,
       it just controls when you find out.
     - **Once OpenTofu is up**: VLAN 50 (`192.168.50.0/24`), the block
       [`vm-provisioning.md`](vm-provisioning.md) reserves for isolated
       experimentation and migration staging — that doc's own Stage 1.5
       is literally "first real run of `restore.yaml`" against a VM
       there. Re-running the drill there afterward is a cheap
       re-verification of the same thing, not the first real test of it.

     Either way: give it its own throwaway name, on its own inventory
     file (a sibling of `inventory/inventory.yaml`, never committed) —
     never the real `inventory.yaml`, so there's no `--limit` typo that
     could reach a real host. In its `host_vars`, list only
     `compose_apps: [{name: wastebin}]` — no `caddy:` block on that
     entry means it's non-routable ([`host-vars.md`](host-vars.md)), so
     the drill needs no DNS or TLS. Deploy it fresh with
     `playbooks/deploy.yaml` against that inventory file.
  4. Restore into it with the already-tested per-app `restore.yaml` —
     against the scratch inventory, with the real archive from step 2:
     ```sh
     ansible-playbook playbooks/bootstrap-secrets.yaml playbooks/restore.yaml \
       -i inventory/scratch-firedrill.yaml --limit scratch-wastebin,localhost \
       -e '{"restore_app": "wastebin", "restore_archive_local_path": "<result.decrypted_path from step 2>", "restore_volumes": ["wastebin_data"]}'
     ```
     One JSON-object `-e` argument, not separate `-e key=value` pairs —
     see [`restore.md`](restore.md) for why that distinction actually
     matters here, not just style.
     Leave `restore_confirm` unset — read the real `pause` prompt's
     "About to STOP wastebin on scratch-wastebin...", with
     `wastebin_data` actually named once (not split into characters —
     that would mean the fix above didn't take), before typing `yes`,
     as a last check that `-i`/`--limit` actually did what you expect.
  5. Confirm the app actually boots clean against the restored data —
     not just that Ansible reported success — then tear the scratch
     host down and `rm -rf ansible/files/restore/scratch/` to clear the
     decrypted plaintext.
  6. Record the result below, dated, and delete the scratch inventory
     file.

  This proves the part that was never provable any other way — a real
  backup decrypts with the real key and the `restore` role correctly
  reconstructs the app — without ever pointing the orchestrator itself
  at production. It doesn't exercise the full batch (step-ca-first
  ordering, abort-on-step-ca-failure, minecraft's two-phase restore);
  the automated scenario above already proves that *logic* against a
  throwaway target, so between the two, both the data path and the
  orchestration logic are covered — just never both at once, and never
  against real infrastructure at the same time.

| Date | Apps covered | SeaweedFS path | Cloud-fallback path | Result |
| :--- | :--- | :--- | :--- | :--- |
| *pending* | — | — | — | Not yet run — this row is a template, not a claim; fill it in after an actual run. See the steps above. |
