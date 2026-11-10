# OpenBao's Rotation Read-Watcher

ADR 0110's per-read alert requirement, and the last piece of
[ADR 0026 (High-value secret read alerts)](../../decisions/0026-detecting-reads-of-high-value-secrets/revision-001.md)
that wasn't already live (the audit device and its logging cap were —
see [`openbao.md`](openbao.md)). Tails `docker logs -f openbao` on
`security`, alerts on any read of the three secret-bearing rotation
credentials, and does nothing else — see
[`docker/openbao/watcher/rotation_read_watcher.py`](../../../docker/openbao/watcher/rotation_read_watcher.py)'s
own docstring for the exact matching logic, confirmed against a real
audit-log capture, not inferred from docs.

## Watched set

All three paths sit under `secret/data/cloud_credentials/rotation/`:

| Provider | Watched path |
| :--- | :--- |
| R2 | `_rotation-key-cloudflare-r2-token` |
| B2 | `_rotation-key-backblaze-b2-application-key` |
| OCI | `_rotation-key-oci-client-secret` |

The identifier-only paths beside them (`…-b2-key-id`, `…-oci-client-id`,
`…-oci-app-id`, `…-oci-domain-url`, `…-oci-created-at`) authenticate
nothing and raise no alert. The alert names the secret that was read. Adding a
rotation credential is one entry in `WATCHED_PATHS` and a row here.

Hand-installed, checked in but never Ansible-deployed — same
convention as `controller.hcl`/`vault-bootstrap.hcl`/`rotation-read-watcher.hcl`:
this is bootstrap-tier OpenBao tooling, not `managed_hosts` application
config.

On restart, the watcher resumes from `/var/lib/rotation-read-watcher/state.json`
(last-alerted read's time and request id) and passes that time as
`docker logs --since`, so a restart doesn't re-alert on every past
read. See the script's own docstring for why the request id is also
checked (`--since` is inclusive of its boundary timestamp, confirmed
live).

A read is recorded in that file only after Telegram accepted its alert. When the send fails, or the
Telegram secrets could not be read at start, the watcher exits non-zero without recording it, and the
unit's `Restart=always` starts it again from the last recorded read, which sends the alert again.

## Expected alerts

`check_credential_expiry.py` reads all three watched secrets on every run: the R2
token in `check_r2()`, the B2 application key through `b2_rotation_api()`, and
the OCI client secret through `oci_identity_domains_client()`. Each weekly run
therefore raises three alerts, one per secret, all naming the role that ran it:
`controller` today, and `cd-agent-credential-expiry` once the check moves to `cd_agent`
([ADR 0020 revision 1 (Automation identity scope)](../../decisions/0020-automation-identity-and-access-scope/revision-001.md)).
The trio is the accepted weekly signal that the credential expiry check ran. The
rotation commands read the same paths when they run, which is also expected. An
alert at any other time, or naming any other role, is not.

## Installing

The watcher's own AppRole (`rotation-read-watcher`) is already provisioned —
[`openbao-reinit-runbook.md`](openbao-reinit-runbook.md)'s step 6. This
picks up from there. A rebuilt `security` has none of it, so these steps run
again on the new VM, and `rebuild_check.host security` fails until they have
([`rebuild-runbook.md`](../disaster-recovery/rebuild-runbook.md#still-done-by-hand)).

1. Copy everything over, from `controller`:

   ```sh
   ssh security 'sudo mkdir -p /opt/rotation-read-watcher /etc/rotation-read-watcher /etc/gatus-push /var/lib/rotation-read-watcher'
   scp docker/openbao/watcher/* security:/tmp/
   ```

2. On `security`, place them and lock down the credential directory:

   ```sh
   sudo mv /tmp/rotation_read_watcher.py /opt/rotation-read-watcher/
   sudo mv /tmp/*.service /tmp/*.timer /etc/systemd/system/
   sudo chmod 700 /etc/rotation-read-watcher /etc/gatus-push
   ```

3. Install `hvac` for the system Python this runs under - apt, not
   pip, as the `seaweedfs_bucket` role does for `boto3` on `storage`,
   rather than fighting PEP 668's externally-managed-
   environment guard. Confirmed on 26.04 (`resolute`): `python3-hvac`
   is 2.3.0, satisfying `pyproject.toml`'s `hvac>=2.3` floor and
   already including `raise_on_deleted_version` (this script's own
   `_read_vault_secret` uses it). Re-check the package version if
   `security` ever moves to a different release - it's much older on
   22.04/24.04 (0.11.2).

   ```sh
   ssh security 'sudo apt install python3-hvac'
   ```

4. Cache the AppRole credentials. From a `vault-bootstrap` session on
   `controller`, each value goes straight into its file on `security`
   without appearing on the terminal or in a command line:

   ```sh
   # [1/3] controller: paste alone; it opens a shell and waits for the secret_id
   cd tools && python3 -m openbao_utils.shell "<vault-bootstrap role_id>"

   # [2/3] inside that shell: paste once its prompt is back
   bao read -field=role_id auth/approle/role/rotation-read-watcher/role-id \
     | ssh security 'sudo tee /etc/rotation-read-watcher/role_id > /dev/null'

   new=$(bao write -f -field=secret_id auth/approle/role/rotation-read-watcher/secret-id) \
     && [ -n "$new" ] \
     && printf '%s' "$new" | ssh security 'sudo tee /etc/rotation-read-watcher/secret_id > /dev/null' \
     && echo "secret_id written"
   unset new
   exit

   # [3/3] controller again: paste after the shell has exited
   ssh security 'sudo chmod 600 /etc/rotation-read-watcher/role_id /etc/rotation-read-watcher/secret_id'
   ```

   The `[ -n "$new" ]` check stops a failed mint from overwriting the file
   with an empty value. Minting again issues another `secret_id` and leaves
   the earlier one valid, so re-run this step only to replace a lost file.

5. Cache the heartbeat's Gatus credentials. The `rotation-read-watcher` job in
   `heartbeat_jobs` already has its token (`gatus-token-rotation-read-watcher`); the unit
   reads the endpoint URL and the bearer header from a curl config, so the
   token never appears in a command line. `sudo` on `security` needs a terminal,
   so the token goes into a temporary file first. `vault-bootstrap` has no access to
   secret data, so this one is a `controller` session:

   ```sh
   # [1/2] controller: paste alone; it opens a shell and waits for the secret_id
   cd tools && python3 -m openbao_utils.shell "$(cat ../ansible/files/secrets/openbao-controller-role-id)"

   # [2/2] inside that shell: paste once its prompt is back
   bao kv get -mount=secret -field=value hosts/security/gatus-token-rotation-read-watcher \
     | ssh security 'umask 077; cat > ~/.gatus-token-rotation'
   exit
   ```

   Then on `security` (`ssh -t security`). `gatus_url` is built in
   `group_vars/all/main.yaml` as `https://`, the Gatus host name, a dot and the main
   domain. This loop asks again for a value that does not start with `https://`,
   ends in a slash or still holds a placeholder in angle brackets, any of which
   makes the URL malformed. Run it on its own, since `read` takes the next line of
   anything pasted after it:

   ```sh
   gatus_url=
   until [[ $gatus_url == https://* && $gatus_url != */ && $gatus_url != *[\<\>]* ]]; do
     read -r -p 'gatus_url (https://..., no trailing slash): ' gatus_url
   done
   ```

   Then write the config:

   ```sh
   t=$(cat ~/.gatus-token-rotation)
   printf 'url = "%s/api/v1/endpoints/backups_rotation-read-watcher/external?success=true"\nrequest = "POST"\nheader = "Authorization: Bearer %s"\n' "$gatus_url" "$t" \
     | sudo tee /etc/gatus-push/gatus-push-rotation-read-watcher.curlrc >/dev/null
   sudo chmod 600 /etc/gatus-push/gatus-push-rotation-read-watcher.curlrc
   unset t; shred -u ~/.gatus-token-rotation
   sudo grep '^url' /etc/gatus-push/gatus-push-rotation-read-watcher.curlrc
   ```

   The last line prints the URL the heartbeat will post to and nothing of the token.

6. Enable and start everything:

   ```sh
   sudo systemctl daemon-reload
   sudo systemctl enable --now rotation-read-watcher.service
   sudo systemctl enable --now rotation-read-watcher-heartbeat.timer
   ```

7. Confirm it's actually alerting, not just running — trigger a real
   read and check both the journal and Telegram:

   ```sh
   # [1/3] security, a second terminal: leave it running to watch the alert arrive
   sudo journalctl -u rotation-read-watcher -f

   # [2/3] controller: paste alone; it opens a shell and waits for the secret_id
   cd tools && python3 -m openbao_utils.shell "$(cat ../ansible/files/secrets/openbao-controller-role-id)"

   # [3/3] inside that shell: paste once its prompt is back. Any one of the three
   # watched secrets works; the value is discarded rather than printed.
   bao kv get -mount=secret -field=value cloud_credentials/rotation/_rotation-key-cloudflare-r2-token > /dev/null
   exit
   ```

## Leftovers from the rename

The `r2-read-watcher` AppRole, its policy and the `gatus-token-r2-read-watcher`
secret are still in OpenBao. Deleting a role, a policy or a KV secret takes a
root session, which neither `vault-bootstrap` nor `controller` has. Nothing
holds the old `secret_id`, and the policy reads only Telegram's secrets. A
re-init does not recreate them, since the runbook provisions only the new role,
so they go then, or in any earlier root session.

## Known gap

`rotation-read-watcher.service` has no alert wired for a watcher that's
stopped doing its job, unlike every other managed service on this
host. The obvious fix doesn't actually work for this unit's shape:
`OnFailure=` only fires once a unit reaches systemd's `failed` state,
and per systemd's own docs a service using `Restart=` only enters
`failed` once its start limits are exhausted (`systemd.unit(5)`,
`OnFailure=`). This unit sets `Restart=always`/`RestartSec=10`
with no `StartLimitIntervalSec=`/`StartLimitBurst=` override, so at
one failure per 10s it never crosses systemd's default burst
threshold — it restarts forever instead. `OnFailure=` would never
fire here, wired or not.

Bounding the restarts to force a `failed` state isn't the fix either:
it trades away the one thing this restart policy is for. This unit's
actual failure mode has been OpenBao being sealed (see
[ADR 0018 (Secrets store unsealing)](../../decisions/0018-unsealing-the-secrets-store-after-restart/revision-000.md)) after a restart or
a re-init, not a real crash — and that clears on its own once someone
unseals it. A bounded restart count would leave the watcher sitting
`failed` silently until a human notices, which is worse than today's
gap.

The replacement: a separate check, run off the same
`rotation-read-watcher-heartbeat.timer` tick, that counts consecutive ticks
where `rotation-read-watcher.service` isn't active and, past **3 in a row
(~30 minutes)**, sends a Telegram alert carrying the tail of
`journalctl -u rotation-read-watcher` — the actual error, not just "it's
down." Not yet built.

30 minutes is what Gatus already gives: the endpoint's 15-minute heartbeat interval (a 10-minute push period plus 5
minutes of slack) puts its own alert between 15 and 30 minutes after the last push. A check that waits for 3 missed
ticks therefore adds the cause, the journal tail, and not an earlier alert; revisit the threshold when it is built.

Needs its own standalone `/etc/telegram-notify/rotation-read-watcher.env`,
populated by hand from the same `hosts/all/telegram/*` values, for
the same reason as the original plan: it must fire even if the
Vault-reachability problem that took the watcher down also takes out
any Vault-backed alerting path.

Until this lands, Gatus's missed-heartbeat alert is the only
backstop. Since this watcher's only job is alerting on reads of the
rotation credentials, any read that happens while it's down goes
undetected until then — Gatus reports the watcher is unhealthy, not
why, and not what happened while it was down.
