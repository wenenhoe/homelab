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
convention as `controller.hcl`/`vault-bootstrap.hcl`/`r2-read-watcher.hcl`:
this is bootstrap-tier OpenBao tooling, not `managed_hosts` application
config.

On restart, the watcher resumes from `/var/lib/r2-read-watcher/state.json`
(last-alerted read's time and request id) and passes that time as
`docker logs --since`, so a restart doesn't re-alert on every past
read. See the script's own docstring for why the request id is also
checked (`--since` is inclusive of its boundary timestamp, confirmed
live).

## Installing

The watcher's own AppRole (`r2-read-watcher`) is already provisioned —
[`openbao-reinit-runbook.md`](openbao-reinit-runbook.md)'s step 6. This
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

3. Install `hvac` for the system Python this runs under - apt, not
   pip, matching `ansible-collections-audit.md`'s `boto3`-on-`storage`
   convention rather than fighting PEP 668's externally-managed-
   environment guard. Confirmed on 26.04 (`resolute`): `python3-hvac`
   is 2.3.0, satisfying `pyproject.toml`'s `hvac>=2.3` floor and
   already including `raise_on_deleted_version` (this script's own
   `_read_vault_secret` uses it). Re-check the package version if
   `security` ever moves to a different release - it's much older on
   22.04/24.04 (0.11.2).

   ```sh
   ssh security 'sudo apt install python3-hvac'
   ```

4. Cache the AppRole credentials (role_id/secret_id from step 7 of the
   reinit runbook):

   ```sh
   printf '%s' '<role_id>'   | sudo tee /etc/r2-read-watcher/role_id > /dev/null
   printf '%s' '<secret_id>' | sudo tee /etc/r2-read-watcher/secret_id > /dev/null
   sudo chmod 600 /etc/r2-read-watcher/role_id /etc/r2-read-watcher/secret_id
   ```

5. Create the heartbeat's push monitor in Kuma's own UI (same one-time
   step every `uptime_kuma_push` consumer needs — see
   [`uptime-kuma.md`](uptime-kuma.md)'s "One-time setup"), then cache
   its URL:

   ```sh
   printf 'UPTIME_KUMA_PUSH_URL=%s\n' '<push url from Kuma>' | \
     sudo tee /etc/uptime-kuma-push/uptime-kuma-push-r2-read-watcher.env > /dev/null
   sudo chmod 600 /etc/uptime-kuma-push/uptime-kuma-push-r2-read-watcher.env
   ```

6. Enable and start everything:

   ```sh
   sudo systemctl daemon-reload
   sudo systemctl enable --now r2-read-watcher.service
   sudo systemctl enable --now r2-read-watcher-heartbeat.timer
   ```

7. Confirm it's actually alerting, not just running — trigger a real
   read and check both the journal and Telegram:

   ```sh
   sudo journalctl -u r2-read-watcher -f &
   cd tools && python3 -m openbao_utils.bao_session "$(cat ../ansible/files/secrets/openbao-controller-role-id)"
   bao kv get -mount=secret cloud_credentials/rotation/_rotation-key-cloudflare-r2-token
   exit
   ```

## Known gap

`r2-read-watcher.service` has no alert wired for a watcher that's
stopped doing its job, unlike every other managed service on this
host. The obvious fix doesn't actually work for this unit's shape:
`OnFailure=` only fires once a unit reaches systemd's `failed` state,
and per systemd's own docs a service using `Restart=` only enters
`failed` once its start limits are exhausted (`systemd.unit(5)`,
`OnFailure=`). This unit sets `Restart=on-failure`/`RestartSec=10`
with no `StartLimitIntervalSec=`/`StartLimitBurst=` override, so at
one failure per 10s it never crosses systemd's default burst
threshold — it restarts forever instead. `OnFailure=` would never
fire here, wired or not.

Bounding the restarts to force a `failed` state isn't the fix either:
it trades away the one thing `Restart=on-failure` is for. This unit's
actual failure mode has been OpenBao being sealed (see
[ADR 0018](decisions/0018-manual-shamir-unseal.md)) after a restart or
a re-init, not a real crash — and that clears on its own once someone
unseals it. A bounded restart count would leave the watcher sitting
`failed` silently until a human notices, which is worse than today's
gap.

The replacement: a separate check, run off the same
`r2-read-watcher-heartbeat.timer` tick, that counts consecutive ticks
where `r2-read-watcher.service` isn't active and, past **3 in a row
(~30 minutes)**, sends a Telegram alert carrying the tail of
`journalctl -u r2-read-watcher` — the actual error, not just "it's
down." Not yet built.

30 minutes is derived from this monitor's real Kuma settings
(Heartbeat Interval 900s, Retries 6, Heartbeat Retry Interval 360s),
not guessed: the first missed check lands at Heartbeat Interval, each
one after that at Heartbeat Retry Interval, and it takes `Retries`
consecutive failures to flip to Down —
`900 + (6 − 1) × 360 = 2700s` (45 minutes) is Kuma's own real
time-to-alert (confirmed against upstream's retry-handling logic,
[louislam/uptime-kuma#4476](https://github.com/louislam/uptime-kuma/pull/4476);
not watched live against this repo's pinned `2.5.3` specifically).
Half of that is 22.5 minutes; the first `r2-read-watcher-heartbeat.timer`
tick past it is the 3rd consecutive miss (30 minutes) — the coarsest
this check can be without changing that timer's own 10-minute
interval, and still a solid ~15-minute head start on Kuma's alert.

Needs its own standalone `/etc/telegram-notify/r2-read-watcher.env`,
populated by hand from the same `hosts/all/telegram/*` values, for
the same reason as the original plan: it must fire even if the
Vault-reachability problem that took the watcher down also takes out
any Vault-backed alerting path.

Until this lands, Kuma's own missed-heartbeat timeout is the only
backstop. Since this watcher's only job is alerting on reads of the
R2 rotation token, any read that happens while it's down goes
undetected until then — Kuma reports the watcher is unhealthy, not
why, and not what happened while it was down.
