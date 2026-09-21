---
id: ADR-0036
revision: 0
type: adr
title: Beszel notification configuration
solution: The token hand-typed into the web UI, DB-resident
summary: How Beszel's Telegram channel is configured, given its notification URL supports no environment variables.
topic: monitoring-alerting
status: accepted
---

# 0036. Beszel notification URL has no env-var support — Telegram token stays hand-typed, DB-resident

**Status:** Accepted

## Context

[`beszel.md`](../../beszel.md) documents the current state: Beszel's
Telegram notification channel is set by hand, **Settings →
Notifications**, pasting
`telegram://<telegram_token>@telegram?chats=<telegram_chatid_monitoring>`
with both values copied in from
`ansible/inventory/group_vars/all/main.yaml`. It lives in the hub's
PocketBase `data` volume alongside the admin account and KEY/TOKEN —
same "only exists after first boot, not Ansible-managed" category,
requiring a full volume wipe to rotate (`beszel.md`'s rotation
runbook, step 6).

Every other Telegram consumer in this repo (`telegram-notify`, `diun`,
`docker-volume-backup`) gets the token through an `.env` file Ansible
renders from Vault (`secrets.md`) — a real secret, injected as an
environment variable, never hand-copied into a running service's own
UI. Beszel is the one exception, purely because its notification
config has no Ansible hook today. The question raised: does Beszel's
web UI, or the shoutrrr library underneath it, resolve an environment
variable reference inside the URL string at connect-time — e.g.
`telegram://${TELEGRAM_TOKEN}@telegram?chats=...` — or store exactly
whatever's typed, literally? Not documented in
[Beszel's own docs](https://beszel.dev/guide/security).

**Confirmed directly from source** (`henrygd/beszel`, fetched fresh),
not trial-and-error against a running instance:

- `internal/alerts/alerts.go`'s alert-dispatch path reads the webhook
  URL via `record.UnmarshalJSONField("settings", &userAlertSettings)`
  — a direct unmarshal of the `user_settings` PocketBase record's
  `settings` JSON field into a `[]string`. Nothing between the stored
  value and this struct field does any templating.
- Each string in that slice passes straight into `sendShoutrrrAlert` →
  `notification_client.go`'s `sendPublicNotification(rawURL, message
  string)`, which hands `rawURL` directly to the vendored shoutrrr
  router's `ExtractServiceName`/`service.Initialize(serviceURL, nil)`
  — parsed as a literal URL, not a template.
- `grep -rn "ExpandEnv\|os.Getenv\|template\." internal/alerts/*.go`
  across the entire alerts package: zero matches. No expansion step
  exists anywhere on this path, in Beszel's own code or the shoutrrr
  fork it vendors.

A definite no, not a "didn't work in this one config" — the string
stored in PocketBase is exactly what gets dialed.

## Decision

The Telegram token stays hand-typed into the web UI, DB-resident,
exactly as `beszel.md` already documents. No env-var workaround exists
to build toward.

## Consequences

- Beszel's Telegram wiring joins its KEY/TOKEN as a second confirmed
  instance of "hand-typed into a web UI, DB-resident" in
  [`0047-first-credential-bootstrap-for-automated-processes/revision-000.md`](../0047-first-credential-bootstrap-for-automated-processes/revision-000.md)'s
  list of this repo's ad hoc Secret Zero answers.
- Rotation is unchanged: `beszel.md`'s existing full-DB-wipe runbook
  is still the only way this value ever changes.
- No new gap from relocating Beszel to GCP
  ([`0042-monitoring-that-survives-loss-of-the-homelab/revision-000.md`](../0042-monitoring-that-survives-loss-of-the-homelab/revision-000.md))
  — the value gets typed in by hand there too, same manual step as
  today.
