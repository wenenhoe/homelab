# Fire Drill: Proving the Restore Path Actually Works

For the backup design this proves — encryption, what's covered — see
[`backup.md`](backup.md), and [`backup-threat-model.md`](backup-threat-model.md) for the threat
model it's built against. For the
per-app and batch restore runbooks themselves, see
[`restore.md`](restore.md).

Two levels of "does this actually work," proving different things:

| Level | What it proves | Touches production |
| :--- | :--- | :--- |
| Molecule scenarios | Discovery, selection and decrypt logic against genuine S3 responses and a throwaway GPG key | No |
| Real fire drill | The whole path: a real backup, the real offline GPG key, a scratch host | Reads the real backup; restores only into the scratch host |

## Automated scenarios

`ansible/roles/restore_discovery/molecule/{default,discovery_and_restore}`
run in CI/dev like any other Molecule scenario, held to the task-coverage
floors in `ansible/molecule-coverage/thresholds.yaml`. `default` renders
the manifest/rclone.conf against synthetic fixtures and asserts on
their content (scope derivation, step-ca ordering, cloud-target
fan-out). `discovery_and_restore` runs the real role against a real
throwaway SeaweedFS target and a real freshly-generated GPG keypair,
proving `restore_all.py`'s own discovery logic — newest-object-by-
timestamp selection, and falling over to a cloud target when
SeaweedFS is unreachable — against genuine S3 responses and a
genuine decrypt, not mocked. Neither touches a real app host or the
real offline private key.

## Real fire drill

This is the only thing that proves the *whole* path end to end: a real
backup, the real offline GPG key, and a scratch/test host, run by hand. **Don't run `restore_all.py`'s full
orchestration for this** — its manifest always resolves each app's
*real* host straight from `app_catalog`/`host_vars`, so it has no
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
   import sys; sys.path.insert(0, 'ansible/scripts')
   import restore_all
   bucket, entries = restore_all.load_manifest()
   entry = next(e for e in entries if e.app == 'wastebin')
   result = restore_all.discover_and_decrypt(entry, bucket)
   print(result.source, result.object_name, result.backup_timestamp)
   print('decrypted at:', result.decrypted_path)
   "
   ```
3. Stand up a scratch host on an isolated segment where nothing
   depends on it, such as VLAN 50 (`192.168.50.0/24`), the block
   [`vm-provisioning.md`](../infra/vm-provisioning.md) reserves for
   isolated experimentation. The host sits behind its own gateway, so
   reach its SSH port through a port forward on that gateway's WAN
   address, limited to the controller's address, and delete the forward
   and its pass rule at teardown.

   Give it its own throwaway name, on its own inventory file next to
   `inventory/inventory.yaml` (`group_vars/all` loads from the inventory
   file's directory) and never committed: add it to `.git/info/exclude`.
   Never the real `inventory.yaml`, so there's no `--limit` typo that
   could reach a real host.

   ```yaml
   ---
   all:
     vars:
       ansible_python_interpreter: /usr/bin/python3.14
       ansible_ssh_private_key_file: ~/.ssh/proxmox_vm_servers
       ansible_become_exe: /usr/bin/sudo.ws
     children:
       managed_hosts:
         hosts:
           scratch-wastebin:
             ansible_host: <gateway WAN address>
             ansible_port: <forwarded port>
             ansible_user: <admin account>
             compose_apps:
               - name: wastebin
                 backup:
                   volumes: []
       reference_hosts:
         hosts:
           security:
             ansible_host: "security.{{ ddns_domain }}"
             ansible_user: secadmin
       controller:
         hosts:
           localhost:
             ansible_connection: local
             ansible_python_interpreter: "{{ ansible_playbook_python }}"
   ```

   - `backup: {volumes: []}` leaves the host with no backup plan, so no
     backup agent is deployed and no S3 credential is needed for a host
     the secret catalog does not know.
   - `security` is outside `managed_hosts` because the secrets play reads
     step-ca's root cert from it. Only `--limit` keeps the plays that
     target `security` off the real host, so list what each play will
     touch first with `--list-hosts`.
   - Every managed host runs the Caddy roles, which render a Caddyfile
     and install a certificate-expiry alert. The scratch host runs no
     Caddy, so `--skip-tags infra` leaves both out. Wastebin joins the
     external `caddy-proxy` network that Caddy's stack creates, so create
     it by hand once Docker is installed. Run the last deploy without `--tags`:
     the tasks that create an app's directory are untagged, and
     `--tags images` skips them.

   ```sh
   cd ansible
   ansible-playbook playbooks/deploy.yaml -i inventory/scratch-firedrill.yaml \
     --limit scratch-wastebin,localhost --list-hosts
   ansible-playbook playbooks/deploy.yaml -i inventory/scratch-firedrill.yaml \
     --limit scratch-wastebin,localhost --tags initial-setup,always --skip-tags infra
   ansible scratch-wastebin -i inventory/scratch-firedrill.yaml -b -m ansible.builtin.shell \
     -a 'docker network inspect caddy-proxy >/dev/null 2>&1 || docker network create caddy-proxy'
   ansible-playbook playbooks/deploy.yaml -i inventory/scratch-firedrill.yaml \
     --limit scratch-wastebin,localhost --skip-tags infra
   ```
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
   `wastebin_data` named once, before typing `yes`,
   as a last check that `-i`/`--limit` actually did what you expect.
5. Confirm the app actually boots clean against the restored data —
   not just that Ansible reported success. Compare the restored volume's
   `state.db` with the archive's: the SHA-256 and the modification time
   must match, since a fresh database can have the same size. Then tear
   the scratch host down, `rm -rf ansible/files/restore/scratch/` to
   clear the decrypted plaintext, and remove the host's `known_hosts`
   entry.
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

## Results

Append a new row per drill — this is a running log, not a single slot.

| Date | Apps covered | SeaweedFS path | Cloud-fallback path | Result |
| :--- | :--- | :--- | :--- | :--- |
| 2026-09-01 | wastebin | Yes — today's `04:30` backup, discovered and decrypted for real | Not exercised this run (covered separately by the automated `discovery_and_restore` scenario) | Pass. Real object → decrypt → extract → volume-swap → redeploy all confirmed against actual content (checksum and original mtime matched the source archive, not a freshly-created empty file). `restore_all.py` passes its `-e` extra-vars to the role as a list (see `restore.md`). App-level write access wasn't independently verified this run. |
| 2026-10-23 | wastebin | Yes — the `04:30` backup of the day before (`services-wastebin-2026-10-22T04-30-01`), discovered and decrypted for real | Not exercised this run (covered separately by the automated `discovery_and_restore` scenario) | Pass. The restored `state.db` had the archive's SHA-256 and original mtime, where the fresh database before it had the same size and a new mtime; wastebin was healthy after the restart. Ran on a scratch host behind its own gateway. App-level write access wasn't verified this run. |
