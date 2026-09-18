---
id: DRAFT-beszel-notification-env-var-not-plaintext-webui
title: "Beszel notifications: env var in the shoutrrr URL, or hand-typed plaintext in the web UI?"
type: draft-adr
status: draft
---

# Beszel notifications: env var in the shoutrrr URL, or hand-typed plaintext in the web UI?

**Status:** Draft — spike about to run, no result yet

## Context

[`beszel.md`](../../beszel.md) already documents the current state
plainly: Beszel's Telegram notification channel is set by hand,
**Settings → Notifications**, pasting
`telegram://<telegram_token>@telegram?chats=<telegram_chatid_monitoring>`
with both values copied in from
`ansible/inventory/group_vars/all/main.yaml`. It lives in the hub's
PocketBase `data` volume alongside the admin account and KEY/TOKEN —
same "only exists after first boot, not Ansible-managed" category, and
the same DB-resident value that has to be re-typed by hand after every
KEY/TOKEN rotation (`beszel.md`'s own rotation runbook, step 6).

Every other Telegram consumer in this repo (`telegram-notify`,
`diun`, `docker-volume-backup`) gets the token through a
`.env` file Ansible renders from Vault
(`secrets.md`) — a real secret, injected as an environment variable,
never hand-copied into a running service's own UI. Beszel is the one
exception, purely because its notification config has no Ansible
hook at all today.

The question: does Beszel's web UI (or the shoutrrr library it uses
underneath) resolve an environment variable reference inside the URL
string at connect-time — e.g. `telegram://${TELEGRAM_TOKEN}@telegram?chats=...`
— or does it store exactly whatever's typed, literally, in its
database? Not documented in [Beszel's own docs](https://beszel.dev/guide/security)
as far as found, and not something to guess at per this repo's
verification discipline — a spike answers it directly instead.

## Decision

Not yet — this draft exists to hold the question and its answer, not
to propose one.

## Assumptions

- **Whether Beszel/shoutrrr does any variable expansion on the
  notification URL before storing or using it.** If yes: the
  `beszel-hub` compose service already has an `.env` (KEY/TOKEN) this
  repo controls, so adding `TELEGRAM_TOKEN`/`TELEGRAM_CHATID` there and
  referencing them in the UI-typed URL would mean the real secret value
  never has to be manually copied out of Vault and pasted into a web
  form — it'd flow through the same Ansible-rendered `.env` pattern as
  every other consumer. If no: this is a hard stop, not a workaround
  to iterate around — the value stays hand-typed, DB-resident, same as
  today. Resolve via a time-boxed spike reading Beszel's own source
  (hub notification-handling code, and whatever shoutrrr version it
  vendors) rather than trial-and-error against a running instance —
  cheaper, and gives a definite yes/no instead of "didn't work in this
  one config."

## Consequences

- If unsupported: Beszel's Telegram wiring stays exactly what it is
  today — one more ad hoc, manually-bootstrapped secret, same
  category [`secret-zero-bootstrap-pattern.md`](secret-zero-bootstrap-pattern.md)
  already lists Beszel's KEY/TOKEN under. Worth naming there
  explicitly once this resolves, rather than left as a separate
  unlinked fact.
- If supported: doesn't remove the "typed once into a web UI" step for
  the initial `telegram://...?chats=...` URL shape itself (chat ID
  routing still has to be entered once), only the secret *value*
  inside it. Still meaningfully better — the token itself becomes
  rotatable the same way every other Vault-backed secret already is,
  without a hand re-copy.
- Relevant to, but doesn't resolve, the bigger question: this is a
  small, single-field instance of exactly the class of problem
  [`secret-zero-bootstrap-pattern.md`](secret-zero-bootstrap-pattern.md)
  is scoped around — worth linking there once decided, not treating
  as fully separate.
