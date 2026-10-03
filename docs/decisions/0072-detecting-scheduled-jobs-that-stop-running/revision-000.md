---
id: ADR-0072
revision: 0
type: adr
title: "Detecting scheduled jobs that stop running"
solution: "Gatus external endpoints in a thin repo-built image: one declaratively configured push endpoint per job, a per-job bearer token, and Telegram alerting routed by group"
summary: "How a job that silently stops running is noticed, with per-job heartbeats, per-topic Telegram routing and no hand-created monitor state."
topic: monitoring-alerting
status: working
related: [ADR-0011, ADR-0012, ADR-0042, ADR-0049]
---

# 0072. Detecting scheduled jobs that stop running

## Problem

`OnFailure=` only reports a job that ran and failed. A job that never ran (a stopped timer, a dead host, a skipped `ExecCondition`) produces no event at all, so silence is ambiguous. Something has to notice the absence of a success.

What has to be true, independent of the tool:

- Each job has its own heartbeat, its own expected interval, and its own credential, so one leaked or rotated credential affects one job.
- Intervals range from hours to about three weeks (the `cert-renewer@` cadence in [`uptime-kuma.md`](../../topics/monitoring/uptime-kuma.md#wiring-a-job-to-its-push-monitor)).
- An alert lands in the Telegram topic that already owns that kind of event ([ADR 0011](../0011-alert-routing-and-noise/revision-000.md)).
- The jobs push; the monitor never needs to reach into a host.
- Rebuilding the monitor from the repo reproduces every monitor and every credential, with no step done by hand in a UI.
- The dashboard is gated, while the push path stays reachable from machine clients that cannot do a browser login.
- The monitor's image carries nothing this use does not need.

## Context

**What exists.** Uptime Kuma push monitors, one per job. A monitor, its notification wiring and its push token exist only inside Kuma's database, created by hand in the UI; [`uptime-kuma.md`](../../topics/monitoring/uptime-kuma.md#one-time-setup-after-first-deploy) lists this as a manual step, and every push URL is then copied into the secret store by hand. Kuma is only used for push monitors in this repo.

**What Kuma's image carries.** Upstream's Dockerfiles build the default image on a base that adds Chromium, fonts and an embedded MariaDB server over a slim base, for browser-engine monitors and the embedded-database option. Neither is used here. A `-slim` variant of each release omits them.

**What a replacement has to match.** The push contract in use today is a `GET` to a URL that embeds the token, sent from `curl` inside a systemd unit (`ansible/roles/uptime_kuma_push`) or inlined in `check-freshness.sh`. Jobs push on success only.

**Gatus, as documented in its README.** An external endpoint is declared in the config file with a `token`, an optional `group` and a `heartbeat.interval`. A job pushes with `POST /api/v1/endpoints/{key}/external?success={success}&error={error}&duration={duration}` and an `Authorization: Bearer` header. `{key}` is `<GROUP_NAME>_<ENDPOINT_NAME>` with ` `, `/`, `_`, `,`, `.`, `#`, `+` and `&` each replaced by `-`. The Telegram provider takes `token`, `id` and `topic-id`, and supports per-group `overrides`. The image is built `FROM scratch`.

**Gatus, as read in its source and run as the v5.37.0 image** against a mock Telegram API with a 15-second heartbeat.

- *Push route.* It sits on the router the source calls unprotected, with a comment that the bearer token is what protects it, so the dashboard's own `security` setting can gate everything else. A missing or invalid `success` parameter returns 400, a missing or non-Bearer header 401, an unknown key 404, and a wrong token 401; each was observed.
- *Heartbeat timing.* The check runs on a ticker started when monitoring starts, so the first check comes one interval after start. At each tick a failure is recorded unless a result newer than one interval exists. A dead job is therefore noticed between one and two intervals after its last push, not exactly one; with a push just after a tick, the alert came 29.9 seconds after it on a 15-second interval.
- *Restarts.* After a process restart the first heartbeat check came one interval after start, and the earlier results were still there from sqlite. The config file is polled every 30 seconds; a changed file stops and restarts monitoring, and the first check after the new config loaded came one interval later. A config change delays detection the same way a process restart does.
- *Alert defaults.* `failure-threshold: 3` and `success-threshold: 2`, counted in results: three missed intervals before an alert and two pushes before it resolves, neither of which suits a job that pushes once a day or once in twenty.
- *Telegram.* An override is matched on the endpoint's group and merged over the defaults; the request body carries `message_thread_id`, as a JSON string, only when the topic ID is non-empty. Each group's alert carried its own topic ID, and the next push sent a resolved message.
- *Config substitution.* `os.ExpandEnv` runs over the file text, with `$$` kept literal, so a literal `$` in the file has to be written `$$`. A value passed in the environment is substituted once and not expanded again: a token containing `$` authenticated correctly.
- *Config validity.* A config with external endpoints alone is rejected at startup with "configuration should contain at least one endpoint or suite"; the check counts regular endpoints and suites only. The v5.37.0 image panics on such a config.
- *Image.* The binary has no health subcommand and the image sets no `USER`. With no shell or `wget` in a `FROM scratch` image, a Compose healthcheck has nothing to exec.

**Precedent for a `FROM scratch` image.** [`docker/wastebin/Dockerfile`](../../../docker/wastebin/Dockerfile) layers a static `wget` and an empty, owned data directory over an upstream scratch image, so Compose can run it non-root with a healthcheck; a workflow builds and pushes it.

**Vigil, as read in its source.** One `reporter_token` for the whole server (HTTP Basic), so no per-job credential. One `[notify.telegram]` block with a single optional `message_thread_id`, so no per-topic routing.

**Upptime** runs as GitHub Actions on a schedule and publishes through GitHub Pages. It would have to reach the monitored services from GitHub's network, which this lab, being LAN and tailnet only, does not expose.

## Decision

Replace Kuma with Gatus for job heartbeats.

- **One external endpoint per job**, generated from the repo, not created in a UI. The endpoint list is rendered from the same definitions that install the push units, so a job and its monitor cannot drift apart.
- **One token per endpoint**, generated and stored by the existing vault-backed secret machinery ([ADR 0067](../0067-where-the-code-that-generates-and-stores-a-vault-backed-secret-lives/revision-000.md)), and passed to Gatus as environment, never written into a world-readable file.
- **One regular self-probe endpoint** besides the external ones: a `GET` of Gatus's own `/health` on localhost, with no alerts, to satisfy the config rule above. It probes nothing else.
- **A thin image built in this repo**, following the wastebin pattern: the pinned upstream image plus a static `wget` for the healthcheck and an empty data directory owned by the non-root user the container runs as.
- **The `cert-renewer@` heartbeat is a daily liveness push, not a push per renewal.** A renewal happens about every 480 hours, and with detection taking up to two intervals a dead renewer could be noticed after the certificate's 720-hour lifetime has ended. Instead a small per-instance timer pushes once a day, only when `step certificate needs-renewal --expires-in <margin>` exits 1, meaning the certificate still has more than the margin left; exit 0, 2 or 255 does not push. Pushes continue while the renewer keeps up and stop once the certificate is inside the margin, so the alert follows within two daily intervals, while the certificate is still valid. The margin must exceed those two intervals; the project chooses it. A failed renewal still reports through its own `OnFailure=`, as today.
- **Alert settings fixed per endpoint:** `failure-threshold: 1`, `success-threshold: 1`, `send-on-resolved: true`.
- **Heartbeat interval** per endpoint is the job's period plus the slack the repo already derives for it (`cron_period_hours` and `backup_freshness_buffer_hours`, [ADR 0068](../0068-where-per-app-backup-settings-get-their-defaults/revision-000.md)). Because detection takes up to two intervals, a job whose failure matters sooner than that gets a more frequent liveness push instead of a longer interval.
- **Telegram routing by group**: one group per existing topic, each an `overrides` entry carrying that topic's `topic-id`.
- **Persistence:** `storage.type: sqlite` on a named volume, so history and open incidents survive a restart.
- **Dashboard gated** by Gatus's own `security` setting. The Caddy route keeps `auth: false`, as Kuma's does, because the push path must bypass forward-auth.
- **Push contract** becomes `POST` with a bearer header, sent by the same systemd units; the push role keeps its shape and changes its `curl` line and its inputs.
- **Cutover** runs both monitors in parallel for one full cycle of the longest interval worth watching, then removes Kuma, its role, its secrets and its catalog entry.

## Alternatives considered

- **Stay on Kuma.** Works today, but every monitor stays hand-made state inside a database, which contradicts the reproducibility requirement.
- **Kuma's `-slim` variant.** Drops the unused browser and embedded database, which answers the footprint requirement but not the reproducibility one. It is adopted only as an interim step while this migration is built, not as the answer.
- **Vigil.** Rejected on credentials and routing: a single shared reporter token and a single Telegram thread cannot express per-job tokens or per-topic alerts.
- **Upptime.** Rejected on topology, see Context.

## Assumptions

- **Claim:** Telegram accepts `message_thread_id` sent as a JSON string, as Gatus sends it.
  **Breaks if wrong:** alerts land in the group's main stream or are rejected, and per-topic routing needs a different mechanism.
  **Checked by:** one real alert sent to the bot's chat and a topic with a Gatus config, since the mock cannot say what Telegram accepts.

## Consequences

Every producer's push call changes. Existing Kuma push URLs and their secrets are retired, and new per-endpoint tokens are created. A second repo-built image joins the build and bump pipeline: an entry in `tools/ci/images/registry.py`, a Dockerfile, a build workflow and a smoke test for the image, as wastebin has, with Renovate bumping the Dockerfile's `FROM`. The registry accepts only tags like `5.37.0`, and Gatus's tags carry a leading `v`, so its tag rule needs a source that strips the `v`, with its unit tests. The `cert-renewer@` monitor changes from a push on renewal to a daily liveness push, which replaces the `OnSuccess=` link on that unit. [`uptime-kuma.md`](../../topics/monitoring/uptime-kuma.md), [`docs/topics/README.md`](../../topics/README.md), the dashboard link, and the Kuma mentions in ADRs 0042 and 0049 and their projects need a follow-up once this is approved; this record changes none of them. The RAM question for the off-site host in [ADR 0049](../0049-monitoring-that-survives-loss-of-the-site/revision-000.md) gets easier, since Gatus is a single static binary, but that is measured, not assumed, there.

## Invariants

- A job with no push produces an alert in its own topic within two of its intervals.
- No two jobs share a push credential.
- No monitor, token or notification setting exists only inside a running instance.
- A certificate that stops being renewed raises an alert while it is still valid.

## Non-goals

Active probing of services beyond the one self-probe (Gatus can do it; this record does not adopt it), replacing Beszel, and where the monitor runs ([ADR 0042](../0042-monitoring-that-survives-loss-of-the-homelab/revision-000.md), [ADR 0049](../0049-monitoring-that-survives-loss-of-the-site/revision-000.md)).
