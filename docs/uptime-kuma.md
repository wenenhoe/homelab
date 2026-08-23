# Uptime Kuma: Live Job Status

`uptime-kuma` is one entry in `app_registry`, deployed on `security` only. See
[`docs/adding-an-app.md`](adding-an-app.md) for the general pattern this follows.

## What it's for

The Telegram topics in [`telegram-notifications.md`](telegram-notifications.md)
only ever hear about **failures** — silence could mean "healthy" or could
mean "nothing has run in days." Kuma's **Push** monitor type closes that
gap: a job `curl`s its own monitor's push URL when it finishes, and if
that ping doesn't arrive within the monitor's configured interval, Kuma
marks it down and fires a notification on its own — a real dead-man's-switch
per job, not just a failure log.

## Why the Caddy route skips Tinyauth

`uptime-kuma`'s Caddy route sets `auth: false`, same reasoning as
`beszel-hub`: push-monitor pings are plain HTTP GETs fired by cron/systemd
jobs on every host, not a browser session. Tinyauth's `forward_auth` would
redirect those GETs to a login page instead of letting them reach Kuma,
silently breaking every push monitor. Kuma's own login still gates the
dashboard itself.

## One-time setup (after first deploy)

1. `ansible-playbook deploy.yaml --limit security` — Kuma starts with an
   empty database.
2. Visit `https://{{ uptime_kuma_host }}.sec.{{ lab_domain }}`, create the
   admin account (first-visit wizard, same as Beszel's hub).
3. **Settings → Notifications**: add a Telegram notification per topic
   that needs live status — bot token/chat ID are the same
   `telegram_token`/`telegram_chat_id` already in `secrets_registry.yaml`,
   plus that topic's own `telegram_topic_id_*` in the **Message Thread ID**
   field. This is what actually routes a monitor's up/down alert into the
   right existing forum topic instead of the group's main stream.
4. Create one **Push** monitor per job to track, assign it the matching
   topic's notification from step 3, and copy its generated push URL —
   each monitor's push token only exists after it's created in the UI,
   the same reason `beszel_hub_key`/`beszel_agent_token` can't be
   templated ahead of time either.

There's no `secrets_registry.yaml` entry for Kuma's own admin account —
unlike Beszel's KEY/TOKEN, nothing outside Kuma itself needs to know it.

## Wiring a job to its push monitor

**Done for `cloud_sync`.** Its `cloud-sync.service` now carries
`OnSuccess=uptime-kuma-push-cloud-sync.service` alongside the existing
`OnFailure=telegram-notify-cloud-sync.service` — see
`ansible/roles/cloud_sync/tasks/main.yaml` and
`ansible/roles/uptime_kuma_push/tasks/install.yaml`. The push URL itself
lives in `secrets_registry.yaml` as `uptime-kuma-push-url-cloud-sync`
(`allow_blank: true`, same first-deploy-blank-is-fine shape as
`beszel-hub-key`) — until the "storage — cloud_sync" Push monitor above
is created and its URL pasted into `ansible/files/secrets/` (or via
`bootstrap_secrets.py`) and `storage` redeployed, the pusher unit just
fails harmlessly on its own (`curl: no URL specified`,
`journalctl -u uptime-kuma-push-cloud-sync`) without affecting
`cloud-sync.service`'s own result or its existing failure alert.

**Only `OnSuccess=` pushes to Kuma** (`?status=up`); `OnFailure=`
stays exactly as it is today, going straight to
`telegram-notify-*`/Telegram, unchanged. Confirmed live on the deployed
2.5.3: an explicit `?status=down` push doesn't mark a Push monitor Down,
it sits in Pending until the Retries × Heartbeat Retry Interval grace
window elapses (fixed upstream in 3.0.0, not yet released — see
[louislam/uptime-kuma#6406](https://github.com/louislam/uptime-kuma/issues/6406)).
Pushing `status=down` on failure would just delay that alert behind the
grace window instead of speeding anything up, on top of duplicating the
already-immediate direct alert. Never pushing a down status sidesteps
the bug entirely rather than depending on a fix landing — Kuma's own
missing-heartbeat detection (the *normal* path, not the buggy explicit
one) is still the backstop for a job that fails silently enough that
even `OnFailure=` never fires (host down, timer masked, unit hung).

Still to do: `cert-renewer@` and `cert-expiry-check` need the same
`OnSuccess=` treatment, and `backup_agent`'s `docker-volume-backup`
instances need a different mechanism entirely — `NOTIFICATION_LEVEL` is
one global setting for the whole container, so there's no way to make it
report every run to Kuma while keeping the existing Telegram alert quiet
on success only. The exact hook to use instead is still to be confirmed
against `docker-volume-backup`'s own docs.

## Runtime config

| Compose file | Image | Network | Notes |
| :--- | :--- | :--- | :--- |
| `docker/uptime-kuma/compose.yaml` | `louislam/uptime-kuma:2.5.3` | Joins `caddy-proxy`, exposes `3001` to Caddy | Persists `data` volume to `/app/data`; healthcheck is the image's own bundled `extra/healthcheck` script |
