---
id: ADR-0072
revision: 0
type: adr
title: "Detecting scheduled jobs that stop running"
solution: "Gatus external endpoints: one declaratively configured push endpoint per job, with a per-job bearer token and Telegram alerting routed by group"
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

## Context

**What exists.** Uptime Kuma push monitors, one per job. A monitor, its notification wiring and its push token exist only inside Kuma's database, created by hand in the UI; [`uptime-kuma.md`](../../topics/monitoring/uptime-kuma.md#one-time-setup-after-first-deploy) lists this as a manual step, and every push URL is then copied into the secret store by hand. Kuma is only used for push monitors in this repo.

**What a replacement has to match.** The push contract in use today is an unauthenticated-looking `GET` to a URL that embeds the token, sent from `curl` inside a systemd unit (`ansible/roles/uptime_kuma_push`) or inlined in `check-freshness.sh`. Jobs push on success only.

**Gatus, as documented in its README.** An external endpoint is declared in the config file with a `token`, an optional `group` and a `heartbeat.interval`. A job pushes with `POST /api/v1/endpoints/{key}/external?success={success}&error={error}&duration={duration}` and an `Authorization: Bearer` header. `{key}` is `<GROUP_NAME>_<ENDPOINT_NAME>` with ` `, `/`, `_`, `,`, `.`, `#`, `+` and `&` each replaced by `-`. The Telegram provider takes `token`, `id` and `topic-id`, and supports per-group `overrides`, so a group maps to a forum topic. Environment variables are substituted in the config file. The image is built `FROM scratch`.

**Gatus, as read in its source.** The push route is registered on the router the source calls unprotected, with a comment that the bearer token is what protects it, so the dashboard's own `security` setting can gate everything else. A heartbeat check runs on a ticker started when Gatus starts, every `heartbeat.interval`; at each tick it records a failure unless a result newer than one interval exists. Alert defaults are `failure-threshold: 3` and `success-threshold: 2`, counted in results: for a heartbeat endpoint that means three missed intervals before an alert and two pushes before it resolves, neither of which suits a job that pushes once per day or once per twenty days.

**Vigil, as read in its source.** One `reporter_token` for the whole server (HTTP Basic), so no per-job credential. One `[notify.telegram]` block with a single optional `message_thread_id`, so no per-topic routing. Nodes are declared in config, and a replica reports its own `interval` in the push body.

**Upptime** runs as GitHub Actions on a schedule and publishes through GitHub Pages. It would have to reach the monitored services from GitHub's network, which this lab, being LAN and tailnet only, does not expose.

## Decision

Replace Kuma with Gatus for job heartbeats.

- **One external endpoint per job**, generated from the repo, not created in a UI. The endpoint list is rendered from the same definitions that install the push units, so a job and its monitor cannot drift apart.
- **One token per endpoint**, generated and stored by the existing vault-backed secret machinery ([ADR 0067](../0067-where-the-code-that-generates-and-stores-a-vault-backed-secret-lives/revision-000.md)) and passed to Gatus as environment, never written into a world-readable file.
- **Alert settings fixed per endpoint:** `failure-threshold: 1`, `success-threshold: 1`, `send-on-resolved: true`.
- **Heartbeat interval** per endpoint is the job's period plus the slack the repo already derives for it (`cron_period_hours` and `backup_freshness_buffer_hours`, [ADR 0068](../0068-where-per-app-backup-settings-get-their-defaults/revision-000.md)).
- **Telegram routing by group**: one group per existing topic, each an `overrides` entry carrying that topic's `topic-id`.
- **Persistence:** `storage.type: sqlite` on a named volume, so history and open incidents survive a restart.
- **Dashboard gated** by Gatus's own `security` setting. The Caddy route keeps `auth: false`, as Kuma's does, because the push path must bypass forward-auth.
- **Push contract** becomes `POST` with a bearer header, sent by the same systemd units; the push role keeps its shape and changes its `curl` line and its inputs.
- **Cutover** runs both monitors in parallel for one full cycle of the longest interval worth watching, then removes Kuma, its role, its secrets and its catalog entry.

## Alternatives considered

- **Stay on Kuma.** Works today, but every monitor stays hand-made state inside a database, which contradicts the reproducibility requirement.
- **Vigil.** Rejected on credentials and routing: a single shared reporter token and a single Telegram thread cannot express per-job tokens or per-topic alerts.
- **Upptime.** Rejected on topology, see Context.

## Assumptions

- **Claim:** the behaviors read from each project's default branch hold in the release this repo would pin.
  **Breaks if wrong:** the alert thresholds, the key format or the unprotected push route differ, and the Decision's settings are wrong.
  **Checked by:** a spike against the pinned image with a short heartbeat interval: push, miss, resolve, and a push with a wrong token.
- **Claim:** a Gatus restart defers every heartbeat check by up to one interval, and a restart is rare enough, or its cost small enough, for the longest interval in use.
  **Breaks if wrong:** after each deploy that restarts Gatus, a dead job on the roughly 480-hour `cert-renewer@` cadence goes unnoticed for up to that long.
  **Checked by:** the same spike, restarting mid-interval; and reading how a config change is applied.
- **Claim:** a container with no shell can still be health-checked in a way the repo's Compose conventions accept.
  **Breaks if wrong:** the app has no healthcheck, unlike the other catalog apps.
  **Checked by:** reading the image and the Compose conventions during the spike.
- **Claim:** per-group Telegram `overrides` can carry each topic's `topic-id` from the existing `telegram_topic_id_*` secrets.
  **Breaks if wrong:** alerts land in the group's main stream instead of the owning topic.
  **Checked by:** the same spike, against a mock Telegram API URL.

## Consequences

Every producer's push call changes. Existing Kuma push URLs and their secrets are retired, and new per-endpoint tokens are created. [`uptime-kuma.md`](../../topics/monitoring/uptime-kuma.md), [`docs/topics/README.md`](../../topics/README.md), the dashboard link, and the Kuma mentions in ADRs 0042 and 0049 and their projects need a follow-up once this is approved; this record changes none of them. The RAM question for the off-site host in [ADR 0049](../0049-monitoring-that-survives-loss-of-the-site/revision-000.md) gets easier, since Gatus is a single static binary, but that is measured, not assumed, there.

## Invariants

- A job with no push inside its interval produces an alert in its own topic.
- No two jobs share a push credential.
- No monitor, token or notification setting exists only inside a running instance.

## Non-goals

Active probing of services (Gatus can do it; this record does not adopt it), replacing Beszel, and where the monitor runs ([ADR 0042](../0042-monitoring-that-survives-loss-of-the-homelab/revision-000.md), [ADR 0049](../0049-monitoring-that-survives-loss-of-the-site/revision-000.md)).
