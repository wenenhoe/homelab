# Telegram Notifications

One bot, one group chat with [Topics](https://telegram.org/blog/topics-in-groups-collectible-usernames)
enabled, a different topic per concern. Four consumers today:

| Concern | Sends via | Topic var |
| :--- | :--- | :--- |
| Image updates (diun) | diun's own Telegram notifier | `telegram_chatid_updates` |
| Host/container monitoring (Beszel) | Beszel's built-in notifications | `telegram_chatid_monitoring` |
| Backup job failures | `docker-volume-backup`'s notifier | `telegram_chatid_backups` |
| Cert renewal failures | `telegram-notify@` (systemd) | `telegram_chatid_certs` / `telegram_topic_id_certs` |

## One-time Telegram-side setup

1. Create the bot via [@BotFather](https://t.me/BotFather); save the token.
2. Create (or pick) a group, enable **Topics** in its settings, add the bot
   as an **admin** — a non-admin bot can't post into an arbitrary topic.
3. Create a topic per row above (e.g. "Updates", "Monitoring", "Backups",
   "Certs").
4. Get the chat ID: forward any message from the group to
   [@shoutrrrbot](https://t.me/shoutrrrbot), or address a message to
   `@shoutrrrbot` from inside the group.
5. Get each topic's ID: open the topic in Telegram, copy a message link
   (`https://t.me/c/<chat>/<topic_id>/<msg_id>`) — the middle number is
   the topic (thread) ID.

## Wiring it into this repo

`telegram_token`/`telegram_chat_id` are the shared bot secrets
(`secrets_registry.yaml`, see [`secrets.md`](secrets.md)). Each concern
above has its own `telegram-topic-id-*` entry, `allow_blank: true` since
Topics is optional — a blank topic ID falls back to posting in the
group's main stream, no code change needed either way (see `main.yaml`'s
`telegram_chatid_*` vars). Bootstrap them the same way as any other
manual secret:

```sh
printf '%s' '<topic-id>' > ansible/files/secrets/telegram-topic-id-updates
```

**Two different address formats, on purpose**: diun, `docker-volume-backup`,
and Beszel all go through [shoutrrr](https://containrrr.dev/shoutrrr/v0.8/services/telegram/)
(or diun's own equivalent), whose convenience syntax is a single
`chat_id:topic_id` string — that's what `telegram_chatid_*` produces.
`telegram-notify@` (below) calls Telegram's Bot API directly instead, and
the real API takes `chat_id` and `message_thread_id` as two separate
parameters — it does **not** understand the colon-combined form. That's
why `telegram_topic_id_certs` exists as a separate, un-prefixed var.

**The bot token's own colon is load-bearing.** A real token from
BotFather is already shaped `<bot-id>:<rest>` — shoutrrr's Telegram
service relies on that exact colon to split the URL's userinfo into
`chat_id`/`message_thread_id`-style username/password parts, then
re-joins and validates them against `^[0-9]+:[a-zA-Z0-9_-]+$`. Any token
missing that shape fails sender setup on every single scheduled run —
not just notification delivery — which for `docker-volume-backup`
specifically means the backup itself never runs either, since sender
setup happens before the backup logic, not after. `telegram_token` here
is always your bot's real token, so this only bites test fixtures using
a placeholder that isn't shaped like one.

## Per-app notes

- **diun**: `docker/diun/configs/env.j2` — `TELEGRAM_CHAT_ID` is
  `telegram_chatid_updates`.
- **Beszel**: not Ansible-managed — its notification channels live in the
  hub's own database, configured once by hand in Settings > Notifications
  (same category as the hub key/token bootstrap, see
  [`beszel.md`](beszel.md#connection-model)). Add a service URL of
  `telegram://<telegram_token>@telegram?chats=<telegram_chatid_monitoring>`.
- **backup_agent**: `NOTIFICATION_URLS` in the role's shared `.env`
  (`ansible/roles/backup_agent/templates/env.j2`) — fires on failed
  backup runs only (`docker-volume-backup`'s own default
  `NOTIFICATION_LEVEL=error`), not on every successful one.
- **Cert renewal**: `ansible/roles/lldap_cert/templates/cert-renewer@.service.j2`
  sets `OnFailure=telegram-notify@%i.service`, a generic systemd
  instantiated unit (`telegram-notify@.service.j2`, same role) that curls
  Telegram's `sendMessage` directly using `/etc/telegram-notify/env`
  (rendered by the role, `no_log: true`). `%i` here is the *invoking*
  unit's own instance (e.g. `lldap`), not a generic failed-unit name —
  this template is coupled to `cert-renewer@`'s naming, not a catch-all
  notifier for arbitrary units. An `ExecCondition` skip (the common,
  nothing-due-for-renewal case) is not a failure and never triggers this
  — systemd only treats exit codes 255 or an abnormal exit as a failure
  for `ExecCondition`.

## Verifying it actually delivers

Molecule (`ansible/roles/lldap_cert/molecule/default`) confirms the
`OnFailure=` link exists, the unit templates correctly, and it loads and
runs under real systemd — it can't confirm a real Telegram message
arrives, since CI has no live bot credentials. Check that part yourself
after deploying:

```sh
# Force the renewal unit to fail and confirm the alert fires
sudo systemctl start telegram-notify@lldap.service
journalctl -u telegram-notify@lldap.service --no-pager -n 20
```

A `curl` exit status other than a clean `0` there (bad token, wrong chat
ID, bot not an admin in the topic's group) means the alert wouldn't have
reached you for a real failure either — worth confirming once per host,
not just trusting the config rendered.
