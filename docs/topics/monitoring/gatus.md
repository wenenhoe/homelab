# Gatus: Job Heartbeats

`gatus` is one entry in `app_catalog`, deployed on `security` beside `uptime-kuma`. See
[`docs/topics/deploy/adding-an-app.md`](../deploy/adding-an-app.md) for the general pattern this follows, and
[ADR 0072](../../decisions/0072-detecting-scheduled-jobs-that-stop-running/revision-000.md) for why it replaces Kuma's push monitors.

## What it's for

`OnFailure=` only reports a job that ran and failed. A job that never ran produces no event at all, so something has to
notice the absence of a success. Each job pushes a heartbeat to its own Gatus *external endpoint*; if no push arrives
within the endpoint's interval, Gatus records a failure and alerts into the Telegram topic that owns that kind of event
(see [`telegram-notifications.md`](telegram-notifications.md)). Every endpoint and token is declared in this repo, so
rebuilding Gatus recreates all of them with nothing done by hand in a UI.

## Declaring a job

`heartbeat_jobs` in `group_vars/all/main.yaml` is the one list of jobs. Each entry is rendered into an external endpoint
by `docker/gatus/configs/config.yaml.j2`:

| Field | Meaning |
| :--- | :--- |
| `id` | The endpoint name. Its token is the `gatus-token-<id>` entry in `secret_catalog.yaml`. |
| `group` | The Telegram topic the alert lands in: its topic ID is `telegram_topic_id_<group>`. Today `backups` and `certs`. |
| `period_minutes` | How often the job pushes. |
| `slack_minutes` | Added to the period to give the heartbeat interval. Defaults to `backup_freshness_buffer_hours` (2 hours). |

A job pushes to the key `<group>_<id>`, which is the endpoint's group and name with ` `, `/`, `_`, `,`, `.`, `#`, `+`
and `&` each replaced by `-` (none of the current ids contain one). The heartbeat interval is `period_minutes` plus the
slack, so a daily job gets 26 hours and the hourly backup freshness check 3 hours. Gatus notices a dead job between one
and two intervals after its last push, not exactly one, so a job whose failure matters sooner gets a more frequent push
rather than a shorter interval.

| Job id | Group | Period | Interval |
| :--- | :--- | :--- | :--- |
| `backup-security`, `backup-services`, `backup-play` | `backups` | 1 hour | 3 hours |
| `cloud-sync` | `backups` | 1 day | 26 hours |
| `r2-read-watcher` | `backups` | 10 minutes | 15 minutes |
| `cert-expiry-security`, `-storage`, `-play`, `-services` | `certs` | 1 day | 26 hours |
| `cert-renewer-lldap`, `cert-renewer-openbao` | `certs` | 1 day | 26 hours |

Each endpoint alerts with `failure-threshold: 1`, `success-threshold: 1` and `send-on-resolved: true`: one missed
interval raises the alert, and the next push resolves it. Gatus's defaults of three and two count results, which would
mean three missed intervals for a job that pushes once a day.

### Adding a job

1. Add an entry to `heartbeat_jobs`.
2. Add `gatus-token-<id>` to `secret_catalog.yaml` as a `hex` entry of length 64, scoped to the host the job runs on.
3. Make the job push on success: see [Pushing from a job](#pushing-from-a-job).

A job with no catalog entry fails the render of Gatus's `.env` instead of getting an empty token. A new `group` also needs
its `telegram-topic-id-<group>` catalog entry and a `telegram_topic_id_<group>` variable in `main.yaml`.

## Tokens

One token per job, generated and kept by the `secrets` role like any other `hex` entry, so a leaked or rotated token
affects one job. They reach Gatus through the container environment: `docker/gatus/configs/env.j2` renders them into
`.env` (mode `0600`, `no_log`), and the config file refers to them as placeholders that Gatus expands when it loads. The
config holds no secret, so it can be world-readable.

`heartbeat_job_tokens` in `main.yaml` maps each job id to its token for any role that needs to push.

## Telegram routing

The `alerting.telegram` block uses the shared bot (`telegram_token`, `telegram_chat_id`) and one `overrides` entry per
group, each carrying that group's topic ID. A blank topic ID leaves the group's alerts in the chat's main stream, the same
fallback every other notifier has. Per-group overrides only replace a topic that is non-empty.

## The dashboard and the push path

Gatus's own `security.basic` gates the dashboard, with the username `admin`. The password is the
`gatus-dashboard-password-bcrypt-base64` secret, a `manual` entry with no `allow_blank`, so a missing value fails the
deploy instead of leaving the dashboard open. Produce it with:

```sh
htpasswd -niBC 9 "" | cut -d: -f2 | tr -d '\n' | base64 -w0
```

which reads the password from stdin, then store it with `cd tools && python3 -m openbao_utils.bootstrap`.

The Caddy route sets `auth: false`, like `uptime-kuma` and `beszel-hub`: pushes are `POST`s from systemd units and cron
jobs on every host, which Tinyauth's `forward_auth` would redirect to a login page. The push route is protected by the
job's bearer token instead, and Gatus's basic auth covers everything else.

## The push contract

```text
POST /api/v1/endpoints/<group>_<id>/external?success=true
Authorization: Bearer <token>
```

`success` is required (a missing or invalid value is a 400). A missing or non-Bearer header is a 401, an unknown key a
404 and a wrong token a 401.

## Pushing from a job

`gatus_push` (`ansible/roles/gatus_push/`) is a library role, included with `tasks_from: install.yaml` and
`gatus_push_job: <id>`. It renders `gatus-push-<id>.service`, a oneshot unit that sends the `POST` above, and
`/etc/gatus-push/gatus-push-<id>.curlrc` (mode `0600`), which holds the endpoint URL and the bearer header. `curl` reads
it with `-K`, so the token is never in the unit's command line, where any local user could read it. The URL comes from
`heartbeat_push_urls` and the token from `heartbeat_job_tokens`, both in `main.yaml`; an id missing from either fails the
include instead of rendering a unit that cannot push.

The job's own unit names it in `OnSuccess=` and never in `OnFailure=`, so a failed run sends nothing and Gatus sees the
missing heartbeat. The including role passes `systemd_reload_gatus: true` to `systemd_reload`, which reloads systemd when
the config or the unit changed.

| Job | Pushed from | Unit that triggers it |
| :--- | :--- | :--- |
| `cloud-sync` | `cloud_sync` on `storage` | `cloud-sync.service` |
| `cert-expiry-<host>` | `caddy_cert_expiry` on each app host | `cert-expiry-check.service` |
| `cert-renewer-<app>` | `step_ca_cert` for each app | `cert-renewer-heartbeat@<app>.service`, below |

Three producers do not use the role:

- **`backup-<host>`** is pushed by `check-freshness.sh` on each backup host, which already decides whether to push at all:
  only when every app's newest backup is within its threshold. The script sends the `POST` itself, passing the URL and
  bearer header to `curl` on stdin (`-K -`) so the token is not in an argument. It tries both monitors even when the
  first push fails, and a failed push fails the unit, so `OnFailure=` alerts as before. A backup host with no matching
  `heartbeat_jobs` entry fails the render instead of skipping the push.
- **`r2-read-watcher`** runs from units copied by hand ([`openbao-r2-read-watcher.md`](../secrets/openbao-r2-read-watcher.md)),
  not from Ansible. `gatus-push-r2-read-watcher.service` has the same shape as the role's, and its curl config is written
  by hand from the job's token.
- **`cd-agent-freshness`** is pushed by the CD agent's `freshness` job. The `cd_agent` role installs
  `gatus-push-cd-agent-freshness.service` and names it in the job's `OnSuccess=` (the job's `heartbeat` field), with the
  URL in the unit and the bearer header in `/etc/gatus-push/cd-agent-freshness.curlrc`. That host holds no secrets, so the
  file is written by hand ([`cd-agent-host.md`](../deploy/cd-agent-host.md#heartbeats)).

### The `cert-renewer@` liveness push

A renewal happens about every 480 hours, so a push per renewal could be noticed only after the certificate had expired.
Instead `cert-renewer-heartbeat@<app>.timer` fires daily at 04:00, and its service runs
`step certificate needs-renewal --expires-in 72h` against the app's certificate volume. Only exit code 1 (the
certificate still has more than 72 hours left) makes the unit succeed and start the push; 0 (inside the margin), 2 (no
certificate file) and 255, or docker failing to run the container, fail it and push nothing. A failed renewal still
reports through `cert-renewer@`'s own `OnFailure=`, which this unit does not repeat. `cert-renewer@` no longer has an
`OnSuccess=`; the liveness unit also starts the Kuma push unit until Kuma is removed.

The margin, `step_ca_cert_heartbeat_margin`, has to sit between two limits. Above 48 hours, so one late push is not an
alert. Below the third of the certificate's life that a healthy certificate always has left (240 hours of the current 720),
because a margin larger than that makes every certificate look overdue and the endpoint alert forever. ADR 0008's
revision 1 shortens the lifetime, so recheck the margin when it lands.

## The self-probe

Gatus rejects a config that has no regular endpoint, so the config carries one: a `GET` of Gatus's own
`http://localhost:8080/health`, with no alert. It probes nothing else.

## Config changes restart the timers

Gatus polls its config file every 30 seconds, and a changed file stops and restarts monitoring: the first heartbeat check
after that comes one interval later, the same as after a process restart. A batch of config changes therefore defers
detection by up to one interval each. The rendered config is seeded into its own `config` volume, and a changed file
restarts the container.

## Runtime config

| Compose file | Image | Network | Notes |
| :--- | :--- | :--- | :--- |
| `docker/gatus/compose.yaml` | `ghcr.io/wenenhoe/gatus` | Joins `caddy-proxy`, exposes `8080` to Caddy | Runs as `10001:10001`; `data` holds the sqlite database at `/data/data.db`, `config` (read-only) holds the rendered config; healthcheck is the image's own `/wget` against `/health` |

The image is built in this repo from the pinned upstream image; see [`ci/gates.md`](../engineering/ci/gates.md) for how it
is built, tagged and checked.

`gatus` has no `backup:` block. The `data` volume holds check history and open-incident state only; the config and every
token are rebuilt from the repo and the secret store. Backing it up would mean stopping the container to copy the
database, which restarts every heartbeat timer, so each backup would defer detection by an interval.

## One-time setup

1. Set `gatus-dashboard-password-bcrypt-base64` as above.
2. `ansible-playbook deploy.yaml --limit security`.
3. Visit `{{ gatus_url }}` and log in as `admin`.

## State today

`cloud_sync`, `cert-expiry-check`, the backup freshness check, the `r2-read-watcher` heartbeat and the two `cert-renewer@`
instances (through their daily liveness push) push to Gatus as well as to Kuma. The CD agent's `freshness` job pushes to
Gatus only, and its token has to be written by hand on that host before its first weekly run.
