# 0014. Telegram group chat with Topics, not direct bot chat

**Status:** Accepted

## Context

The original Telegram setup was a bot the operator chatted with
directly, one-on-one — every alert (image updates, backup failures,
cert renewals, monitoring) landed in the same single conversation,
with nothing to distinguish which concern a given message belonged to
beyond reading its text.

## Decision

Move to a group chat with [Topics](https://telegram.org/blog/topics-in-groups-collectible-usernames)
enabled, the bot added as an admin, and a separate topic per concern
(Updates, Monitoring, Backups, Certs) — see
[`telegram-notifications.md`](../telegram-notifications.md) for the
full concern-to-topic mapping and setup steps.

## Consequences

Alerts are now segmented by concern at the transport level, not just
by message content — a failing backup and a routine image-update
notice land in physically different topics, so noticing a real problem
doesn't depend on reading past routine chatter. The cost: setup is a
few more one-time steps (create a group, enable Topics, add the bot as
admin, get a chat ID and a topic ID per topic) instead of just
messaging a bot directly, and every consumer needs both a chat ID and
a topic ID rather than a chat ID alone.
