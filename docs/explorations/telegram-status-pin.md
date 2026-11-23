---
id: EXP-telegram-status-pin
title: "Should a Telegram topic show the latest state of its concern, and who would keep it current?"
type: exploration
status: open
summary: "Whether each topic should carry a pinned message edited in place with its concern's last state, beyond the static header, and whether each notifier, one poster or nothing at all keeps it true."
topic: monitoring-alerting
related: [ADR-0011, ADR-0072]
---

# Should a Telegram topic show the latest state of its concern, and who would keep it current?

Each topic opens on a pinned header that says what the topic is for. Opening the group does not say whether the last backup, certificate check or host check passed, because a topic only shows the moments something failed. A pinned message edited in place would show the last state, and it is not built.

## What bears on it

- **Who posts.** Five senders feed the topics through three mechanisms: Beszel and `docker-volume-backup` through shoutrrr, the three systemd notifiers through a `curl` of the Bot API in the shared `telegram_notify` role, and Gatus through its own `alerting.telegram` block.
- **What the header does.** One control-node playbook posts it and pins it once, and records each topic's message id in a gitignored file, since the Bot API has no "already pinned?" query.
- **What a notifier says.** Every sender speaks only when something is wrong, and a good run is silence, so none holds today what a pin would say after one.
- **What Gatus holds.** It holds the state of every endpoint declared in this repository, grouped by topic.
- **The cost of a stale pin.** A pin that reads "ok" after its writer stopped is a false assurance, and the repository already treats a job that stops running as a failure in its own right ([ADR 0072 (Job heartbeats)](../decisions/0072-detecting-scheduled-jobs-that-stop-running/revision-000.md)).

Still to check: whether shoutrrr can edit a message at all, and whether every concern that has a topic is also a Gatus endpoint.

## Options

- **Each notifier edits its topic's pin.** The state is written where it is known. It touches all five senders, and the shoutrrr ones may not be able to edit, so they would change mechanism first.
- **One poster reads Gatus and edits every pin.** One writer and one place to keep alive, with the pin as a pure function of Gatus's state. It covers only what Gatus knows, and the poster is one more job that must itself be noticed when it stops.
- **Keep the header only.** Nothing new to run or to go stale. Opening the group still says nothing about the last good run.

## Leaning

Keep the header only until a design can show its own staleness, for instance a pin that carries the time it was last written. What would change it: a failure that went unnoticed because no topic showed the last state.
