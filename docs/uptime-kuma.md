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

**Done for `cloud_sync`, `cert-renewer@lldap`, and `cert-expiry-check`
(all 4 hosts).** Same shape throughout — `OnSuccess=` push, `OnFailure=`
unchanged.

`cert-renewer@` has one real difference from the other two: its
`ExecCondition` skips the run entirely on the vast majority of the
timer's 15-minute ticks (not due for renewal yet), and a skip is neither
success nor failure at the systemd level — `OnSuccess=`/`OnFailure=`
only fire on a genuine completed run. With step-ca's default
`defaultTLSCertDuration` of 24h (unconfigured in this repo, confirmed —
no `claims` override exists anywhere in `ca.json`/provisioner config)
and `step ca renew`'s own ⅔-of-lifetime renewal trigger, a real renewal
— and therefore a real push — happens roughly once a day, not every 15
minutes. Size that Push monitor's Heartbeat Interval accordingly (~28h,
with sixth-of-that-scale retries/grace, the same shape as `cloud_sync`'s
own once-daily cadence below) — a shorter interval will false-alarm on
every ordinary skip.

`cert-renewer@` is also a genuine systemd `@`-template, shared by any
future cert under it — not just lldap's. Unlike `telegram_notify@`
(one shared bot, one shared credentials file works for every instance),
each cert needs its *own* Kuma monitor and push URL, so `OnSuccess=`
resolves to `uptime-kuma-push-cert-renewer-%i.service`, and each
consuming role installs its own concretely-named unit (`lldap_cert`
installs `uptime-kuma-push-cert-renewer-lldap.service` — see its own
`tasks/main.yaml`). A future instance with no matching unit installed
just gets a harmless "unit not found" line in the journal at trigger
time — standard systemd dependency-resolution behavior, not a failure
of the renewal itself.

`cert-expiry-check` has no `ExecCondition` — every timer tick genuinely
runs the check, so it behaves exactly like `cloud_sync`: one push per
host per day. It also runs on **all 4 app_hosts**, so it needed 4
separate `secrets_registry.yaml` entries and its own push URL
(`uptime_kuma_push_url_cert_expiry`) is a single `inventory_hostname`-keyed
lookup in `group_vars/all/main.yaml` rather than 4 separate `host_vars`
entries — the role already runs once per host via Ansible's normal loop,
so no per-host role logic was needed beyond that one dynamic var.

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

**Done for `backup_agent`, via a different mechanism than the other
three, and one push per *host* rather than per app.** `docker-volume-backup`'s
own exec-hook labels (`copy-post` etc.) need Docker `exec` access, which
this host's socket-proxy deliberately doesn't grant (`EXEC=1` isn't in
`CONTAINERS=1, POST=1, INFO=1`) — widening that would mean "run
arbitrary commands inside any labeled container" as a standing
capability, a real security trade-off for a nice-to-have liveness
signal, not something to grant quietly. Instead, a new host-side
`check-freshness.timer`/`.service` (hourly, outside the backup container
entirely) checks whether *every* app's newest object in SeaweedFS is
within `offsite_backup_freshness_hours` (26h default) using `rclone lsf
--max-age`, and pushes **once, only if every app on that host is
fresh** — see
`ansible/roles/backup_agent/templates/check-freshness.sh.j2`. One stale
app suppresses the whole host's push; Kuma shows "this host's backups"
as one monitor, not one per app — which specific app is stale is only
visible in that unit's own journal.

This needs no new credential or privilege: it reuses the same
already-scoped `seaweedfs_s3_access_key`/`secret_key` each host already
has write access with (see `docs/disaster-recovery.md`) — read is
strictly less than what it can already do. One push per host, not per
app, also means **a future app added to an existing host needs no new
config at all** — no new `secrets_registry.yaml` entry, no new
`host_vars` key. A genuinely new *host* running `backup_agent` for the
first time is the only case that needs new setup (one new
`secrets_registry.yaml` entry, one new `backup_freshness_push_url` in
that host's `host_vars`) — a much rarer event than adding an app.

`rclone` (actively maintained) runs the check, not `mc` — MinIO archived
both `minio/minio` and `minio/mc` on Docker Hub as part of their move to
a commercial "AIStor" product, freezing the last published `mc` image
with no further security patches.

The script's own exit code distinguishes three outcomes per app, not
two — collapsing "ran fine, nothing fresh yet" into the same failure
path as "rclone/docker itself couldn't run" would alert on ordinary
staleness constantly, defeating the point of leaving that to Kuma's own
missing-heartbeat timeout instead:

| Outcome | Counts toward the push | Triggers `OnFailure=` |
| :--- | :--- | :--- |
| Fresh backup found | Yes | No |
| Ran fine, nothing fresh yet | No | No — silent, Kuma's own timeout catches persistent staleness |
| `rclone`/`docker` itself failed | No | Yes — a real infra problem, not a backup problem |

A **centralized checker on `storage`** (reusing `cloud_sync`'s own
existing bucket-wide `seaweedfs-cloud-sync-reader` credential) was
considered and rejected — not on privilege-cost grounds (there isn't
one, `storage` already holds that broader credential), but because it
would need `hostvars['services'].compose_apps`-style cross-host fact
access to know what to check, which is only populated when those hosts
are part of the *same* playbook run. That breaks silently under
`ansible-playbook deploy.yaml --limit services` — the checker would work
off stale/absent data for other hosts until someone remembers to also
run the full, unlimited playbook. The current per-host design keeps
every host self-contained, consistent with every other check in this
project.

Every push URL across all four mechanisms above (`cloud_sync`,
`cert-renewer-lldap`, the 4 `cert-expiry-check` entries, and the 3
per-host `backup_freshness_push_url` entries) still needs its matching
Push monitor created in Kuma's UI and the real URL pasted into
`ansible/files/secrets/` (or via `bootstrap_secrets.py`) before any of
this actually reports anywhere.

## Runtime config

| Compose file | Image | Network | Notes |
| :--- | :--- | :--- | :--- |
| `docker/uptime-kuma/compose.yaml` | `louislam/uptime-kuma:2.5.3` | Joins `caddy-proxy`, exposes `3001` to Caddy | Persists `data` volume to `/app/data`; healthcheck is the image's own bundled `extra/healthcheck` script |
