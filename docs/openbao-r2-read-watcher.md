# OpenBao's R2 Read-Watcher

ADR 0024's per-read alert requirement, and the last piece of
[ADR 0026](decisions/0026-openbao-audit-device-and-r2-per-read-watcher.md)
that wasn't already live (the audit device and its logging cap were —
see [`openbao.md`](openbao.md)). Tails `docker logs -f openbao` on
`security`, alerts on any read of the R2 rotation token's Vault path,
and does nothing else — see
[`docker/openbao/watcher/r2_read_watcher.py`](../docker/openbao/watcher/r2_read_watcher.py)'s
own docstring for the exact matching logic, confirmed against a real
audit-log capture, not inferred from docs.

Hand-installed, checked in but never Ansible-deployed — same
convention as `controller.hcl`/`vault-bootstrap.hcl`/`r2-read-watcher.hcl`
and the `bao-*.sh` scripts: this is bootstrap-tier OpenBao tooling, not
`managed_hosts` application config.

On restart, the watcher resumes from `/var/lib/r2-read-watcher/state.json`
(last-alerted read's time and request id) and passes that time as
`docker logs --since`, so a restart doesn't re-alert on every past
read. See the script's own docstring for why the request id is also
checked (`--since` is inclusive of its boundary timestamp, confirmed
live).

## Installing

The watcher's own AppRole (`r2-read-watcher`) is already provisioned —
[`openbao-reinit-runbook.md`](openbao-reinit-runbook.md)'s step 7. This
picks up from there.

1. Copy everything over, from `controller`:

   ```sh
   ssh security 'sudo mkdir -p /opt/r2-read-watcher /etc/r2-read-watcher /etc/uptime-kuma-push /var/lib/r2-read-watcher'
   scp docker/openbao/watcher/* security:/tmp/
   ```

2. On `security`, place them and lock down the credential directory:

   ```sh
   sudo mv /tmp/r2_read_watcher.py /opt/r2-read-watcher/
   sudo mv /tmp/*.service /tmp/*.timer /etc/systemd/system/
   sudo chmod 700 /etc/r2-read-watcher
   ```

3. Cache the AppRole credentials (role_id/secret_id from step 7 of the
   reinit runbook):

   ```sh
   printf '%s' '<role_id>'   | sudo tee /etc/r2-read-watcher/role_id > /dev/null
   printf '%s' '<secret_id>' | sudo tee /etc/r2-read-watcher/secret_id > /dev/null
   sudo chmod 600 /etc/r2-read-watcher/role_id /etc/r2-read-watcher/secret_id
   ```

4. Create the heartbeat's push monitor in Kuma's own UI (same one-time
   step every `uptime_kuma_push` consumer needs — see
   [`uptime-kuma.md`](uptime-kuma.md)'s "One-time setup"), then cache
   its URL:

   ```sh
   printf 'UPTIME_KUMA_PUSH_URL=%s\n' '<push url from Kuma>' | \
     sudo tee /etc/uptime-kuma-push/uptime-kuma-push-r2-read-watcher.env > /dev/null
   sudo chmod 600 /etc/uptime-kuma-push/uptime-kuma-push-r2-read-watcher.env
   ```

5. Enable and start everything:

   ```sh
   sudo systemctl daemon-reload
   sudo systemctl enable --now r2-read-watcher.service
   sudo systemctl enable --now r2-read-watcher-heartbeat.timer
   ```

6. Confirm it's actually alerting, not just running — trigger a real
   read and check both the journal and Telegram:

   ```sh
   sudo journalctl -u r2-read-watcher -f &
   docker exec -e BAO_TOKEN -e BAO_SKIP_VERIFY=true openbao \
     bao kv get -mount=secret cloud_credentials/rotation/_rotation-key-cloudflare-r2-token
   ```

## Known gap

`r2-read-watcher.service` has no `OnFailure=` wired to
`telegram_notify` yet, unlike every other managed service on this
host. Deliberately deferred, not forgotten: that notification path
needs its own standalone Telegram credentials file (it must fire even
if the crash that triggered it took Vault reachability down too — the
watcher's own alerting can't be the thing that tells you the watcher
died). Needs a `/etc/telegram-notify/r2-read-watcher.env`, populated by
hand from the same `hosts/all/telegram/*` values, before wiring
`OnFailure=telegram-notify-r2-read-watcher.service` into the unit
above. Until then, Kuma's own missed-heartbeat timeout is the only
backstop if the process dies outright.
