# Replace r2_read_watcher.py with a proper audit pipeline (e.g. Wazuh)?

**Status:** Draft — exploratory, not scoped for building yet

## Context

`docker/openbao/watcher/r2_read_watcher.py` (ADR 0026) is a
purpose-built Python watcher for exactly one thing: alerting on reads
of the R2 admin token. Confirmed: no SIEM/audit-log tooling (Wazuh or
otherwise) exists anywhere in this repo today — this is a genuinely
new direction, not a gap in an existing setup.

The instinct is reasonable on its face: a single-purpose watcher
doesn't generalize, and this repo already has a recognizable pattern —
narrow, independently-written alerting code showing up in more than
one place (this watcher, `check_freshness.py`'s Telegram call,
`telegram_notify`/`telegram_topic_pins` roles, `uptime_kuma_push`) —
similar in shape to the OpenBao-client duplication already found this
session, just for alerting instead of secrets access.

## Not yet evaluated

- Whether Wazuh specifically fits a single-operator homelab's resource
  budget and operational overhead, versus a lighter log-shipping
  target, versus not centralizing this at all.
- What `r2_read_watcher.py`'s specific detection (a narrow, low-volume,
  high-signal credential-read alert) would need to look like once
  reimplemented as a generic SIEM rule, and whether that's actually as
  reliable as the current purpose-built check.
- Which of `check_freshness.py`, `telegram_notify`, `telegram_topic_pins`,
  and `uptime_kuma_push` would actually feed into it, versus staying
  separate because they're already fine — "what should hook up to
  Wazuh" is the real open question, not "replace everything with it."

## Why this is its own draft, not a stage of an existing project

This isn't a library swap like the rest of this session's drafts — it's
a new piece of infrastructure with its own resource footprint,
operational surface, and maintenance burden. It doesn't belong under
`openbao-python-client-hardening.md` (that's about which Python client
talks to OpenBao, not what watches for suspicious access) or
`ansible-collections-audit.md` (that's about existing roles' task
shape, not new infrastructure). Needs its own scoping pass before it's
more than a name on a list.
