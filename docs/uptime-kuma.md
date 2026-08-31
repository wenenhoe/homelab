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

**Done for `cloud_sync`, `cert-renewer@lldap`, `cert-expiry-check` (all 4
hosts), and `backup_agent`.** Every one of them pushes on success only —
`OnFailure=` always stays exactly as it was before Kuma existed, going
straight to `telegram-notify-*`, unchanged. Never pushing an explicit
`status=down` is deliberate: on the deployed 2.5.3, that sits in Pending
rather than marking Down until a retry-grace window elapses (fixed
upstream in 3.0.0 — [louislam/uptime-kuma#6406](https://github.com/louislam/uptime-kuma/issues/6406)),
so Kuma's own missing-heartbeat detection is the real backstop for a job
that fails silently enough that even `OnFailure=` never fires.

Two different push mechanisms are in use, not one:

- `cloud_sync`, `cert-renewer@lldap`, `cert-expiry-check` each install a
  dedicated `uptime-kuma-push-*.service` unit via the shared
  `uptime_kuma_push` role (`ansible/roles/uptime_kuma_push/`).
- `backup_agent` inlines its own `curl` directly inside
  `check-freshness.sh` instead, since its push is conditional on an
  aggregate check across every app on the host, not a single job's own
  exit code — see below.

`cert-renewer@` has one real difference from the other two systemd-unit
consumers: its `ExecCondition` skips the run entirely on the vast
majority of the timer's 15-minute ticks (not due for renewal yet), and a
skip is neither success nor failure at the systemd level. This repo
overrides step-ca's own 24h default to a 720h (30-day) cert lifetime
(see [`step-ca.md`](step-ca.md#why-the-cert-duration-is-720h-not-step-cas-own-24h-default)),
so with `step ca renew`'s ⅔-of-lifetime trigger, a real push happens
roughly once every 20 days (~480h) — size that monitor's Heartbeat
Interval accordingly (with margin above ~480h), not to the 15-minute
tick rate or a daily cadence.

`cert-renewer@` is also a genuine systemd `@`-template, shared by any
future cert under it — not just lldap's. Unlike `telegram_notify@` (one
shared bot, one shared credentials file works for every instance), each
cert needs its *own* Kuma monitor and push URL, so `OnSuccess=` resolves
to `uptime-kuma-push-cert-renewer-%i.service`, and each consuming role
installs its own concretely-named unit (`lldap_cert` installs
`uptime-kuma-push-cert-renewer-lldap.service`). A future instance with
no matching unit installed just gets a harmless "unit not found" line in
the journal at trigger time — standard systemd dependency-resolution
behavior, not a failure of the renewal itself.

`cert-expiry-check` has no `ExecCondition` — every tick genuinely runs,
so it pushes once per host per day like `cloud_sync`. It runs on all 4
app_hosts, so its push URL (`uptime_kuma_push_url_cert_expiry`) is a
single `inventory_hostname`-keyed lookup in `group_vars/all/main.yaml`
rather than 4 separate `host_vars` entries.

`backup_agent` pushes **once per host, not once per app** — a new
`check-freshness.timer`/`.service` (hourly, host-side, entirely outside
the backup container) checks whether *every* app's newest SeaweedFS
object is within `offsite_backup_freshness_hours` (26h default, via
`rclone lsf --max-age`; `rclone` not `mc` — MinIO archived `mc`'s Docker
Hub image), and pushes only if all of them are. One stale app suppresses
the whole host's push; which specific app is stale is only visible in
that unit's own journal, not from Kuma. This needs no new credential:
it reuses each host's own already-scoped SeaweedFS write key (read is
strictly less access than that). One push per host also means a future
app added to an *existing* host needs zero new config — only a
genuinely new host running `backup_agent` needs a new
`secrets_registry.yaml` entry and `host_vars` key. (A checker
centralized on `storage` was considered — no privilege cost, since
`cloud_sync` already holds a bucket-wide read credential there — but
rejected: it would need cross-host `hostvars` fact access that isn't
populated under `ansible-playbook deploy.yaml --limit <host>`, breaking
silently on exactly the partial-deploy flow this repo's `--limit`
pattern is built around.)

The freshness script's exit code distinguishes three outcomes per app,
not two — collapsing "ran fine, nothing fresh yet" into the same
failure path as "rclone/docker itself couldn't run" would alert on
ordinary staleness constantly, defeating the point of leaving that to
Kuma's own timeout instead:

| Outcome | Counts toward the push | Triggers `OnFailure=` |
| :--- | :--- | :--- |
| Fresh backup found | Yes | No |
| Ran fine, nothing fresh yet | No | No — silent, Kuma's own timeout catches persistent staleness |
| `rclone`/`docker` itself failed | No | Yes — a real infra problem, not a backup problem |

Every push URL across all mechanisms above (`cloud_sync`,
`cert-renewer-lldap`, the 4 `cert-expiry-check` entries, and the 3
per-host `backup_agent_freshness_push_url` entries) still needs its matching
Push monitor created in Kuma's UI and the real URL pasted into
`ansible/files/secrets/` (or via `bootstrap_secrets.py`) before any of
this actually reports anywhere.

## Runtime config

| Compose file | Image | Network | Notes |
| :--- | :--- | :--- | :--- |
| `docker/uptime-kuma/compose.yaml` | `louislam/uptime-kuma:2.5.3` | Joins `caddy-proxy`, exposes `3001` to Caddy | Persists `data` volume to `/app/data`; healthcheck is the image's own bundled `extra/healthcheck` script |
