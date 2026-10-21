# Gatus: Job Heartbeats

`gatus` is one entry in `app_catalog`, deployed on `security` only. See
[`docs/topics/deploy/adding-an-app.md`](../deploy/adding-an-app.md) for the general pattern this follows, and
[ADR 0072](../../decisions/0072-detecting-scheduled-jobs-that-stop-running/revision-000.md) for why it is the job-heartbeat monitor.

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

## Proving an alert

An endpoint alerts after one failed result and resolves on the next success, so a deliberate failure push shows its group's topic
without stopping a job. Take the job's token from OpenBao inside a `vault-bootstrap` session, and pass it to `curl` as a config on
stdin so it is not in an argument:

```sh
URL="$GATUS_URL/api/v1/endpoints/<group>_<id>/external"
t=$(bao kv get -mount=secret -field=value hosts/<host>/gatus-token-<id>)
printf 'header = "Authorization: Bearer %s"\n' "$t" | curl -fsS -X POST -K - "$URL?success=false"
# the alert arrives in the group's topic; then resolve it:
printf 'header = "Authorization: Bearer %s"\n' "$t" | curl -fsS -X POST -K - "$URL?success=true"
unset t
```

A real producer's next scheduled push also resolves it. This proves the routing and the resolved message. Detecting a job that
stops is a separate path (a missed heartbeat), shown by stopping a timer: the [`r2-read-watcher`](../secrets/openbao-r2-read-watcher.md)
heartbeat is the quickest, with a 15-minute interval.

## Telegram routing

The `alerting.telegram` block uses the shared bot (`telegram_token`, `telegram_chat_id`) and one `overrides` entry per
group, each carrying that group's topic ID. A blank topic ID leaves the group's alerts in the chat's main stream, the same
fallback every other notifier has. Per-group overrides only replace a topic that is non-empty.

## The dashboard and the push path

Gatus's own `security.basic` gates the dashboard's data, with the username `admin`: the API, including `/api/v1/endpoints/statuses`, answers `401` without it, while the static page shell is served to anyone. The password is the
`gatus-dashboard-password-bcrypt-base64` secret, a `manual` entry with no `allow_blank`, so a missing value fails the
deploy instead of leaving the dashboard open. Produce it with:

```sh
htpasswd -niBC 9 "" | cut -d: -f2 | tr -d '\n' | base64 -w0
```

which reads the password from stdin, then store it with `cd tools && python3 -m openbao_utils.bootstrap`.

The Caddy route sets `auth: false`, like `beszel-hub`: pushes are `POST`s from systemd units and cron
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
- **The CD agent's `freshness` job** has no endpoint yet. The `cd_agent` role can install a push unit for any job that sets
  `heartbeat`, and the host holds no secrets, so the curl config is written by hand; the steps, and the three lines that add the
  endpoint when the host is deployed, are in [`cd-agent-host.md`](../deploy/cd-agent-host.md#heartbeats).

### The backup freshness check

`check-freshness.timer` runs hourly on each backup host, outside the backup container: `offen/docker-volume-backup`'s own
exec-hook labels need Docker `exec` access, which the host's socket proxy deliberately refuses. It checks, with `rclone lsf
--max-age` (`rclone`, not `mc`, whose Docker Hub image MinIO archived), that every app's newest SeaweedFS object is within
that app's own threshold, and pushes only if all of them are. It pushes once per host, not once per app: every app's
credential is scoped to the host's own `{host}-*` prefix, so an app added to an existing host needs no new configuration.
[ADR 0012 (Backup verification)](../../decisions/0012-verifying-backups-actually-land/revision-000.md) explains why it
runs per host and not as one checker on `storage`.

An app's threshold comes from its own resolved cron, not from a value set by hand: the `cron_period_hours` filter in
`ansible/filter_plugins/` gives the longest gap between two consecutive firings, and `backup_freshness_buffer_hours` is
added for the backup's duration and scheduling slack. An app on a different cadence gets a threshold that matches it, and
nothing falls out of sync if its cron changes. One stale app suppresses the whole host's push; which one is only visible
in the unit's journal.

The script's exit code separates three outcomes per app, because treating "nothing fresh yet" like a failure would alert
on ordinary staleness constantly, when the missed heartbeat already covers it:

| Outcome | Counts toward the push | Triggers `OnFailure=` |
| :--- | :--- | :--- |
| Fresh backup found | Yes | No |
| Ran fine, nothing fresh yet | No | No — silent, the missed heartbeat catches persistent staleness |
| `rclone` or `docker` itself failed | No | Yes — an infrastructure problem, not a backup problem |

### The `cert-renewer@` liveness push

A renewal happens about every 480 hours, so a push per renewal could be noticed only after the certificate had expired.
Instead `cert-renewer-heartbeat@<app>.timer` fires daily at 04:00, and its service runs
`step certificate needs-renewal --expires-in 72h` against the app's certificate volume. Only exit code 1 (the
certificate still has more than 72 hours left) makes the unit succeed and start the push; 0 (inside the margin), 2 (no
certificate file) and 255, or docker failing to run the container, fail it and push nothing. A failed renewal still
reports through `cert-renewer@`'s own `OnFailure=`, which this unit does not repeat. `cert-renewer@` no longer has an
`OnSuccess=`.

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

1. Store `gatus-dashboard-password-bcrypt-base64` as above. `python3 -m openbao_utils.bootstrap` writes it to OpenBao directly, so it needs no deploy first; the deploy's secrets play fails without it.
2. `ansible-playbook deploy.yaml --limit security,localhost`. The secrets play runs on `localhost`, so a limit of `security` alone skips it and the config has no tokens to render.
3. Visit `{{ gatus_url }}` and log in as `admin`.

## Checking the endpoints

With `GATUS_URL` set to `gatus_url` (no trailing slash, which makes the path `//api` and a `404`) and the dashboard password in `PW`, list each endpoint's latest result:

```sh
curl -su "admin:$PW" "$GATUS_URL/api/v1/endpoints/statuses?pageSize=100" \
  | jq -r '.[] | [.group, .name, (if (.results|length)==0 then "NO RESULT" else (.results[-1].success|tostring) end)] | @tsv' | sort
```

An endpoint that has never been pushed to is missing from the list until its first interval passes. Use `tostring`: `jq`'s `//` treats `false` as absent, so `.success // "NO RESULT"` shows a failed check as `NO RESULT`.

## State today

`cloud_sync`, `cert-expiry-check`, the backup freshness check, the `r2-read-watcher` heartbeat and the two `cert-renewer@`
instances (through their daily liveness push) push to Gatus, and nothing else monitors them.
