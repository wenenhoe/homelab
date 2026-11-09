---
id: EXP-host-alert-declaration
title: "Where should a host-resource alert be declared so that a rebuilt monitor brings it back?"
type: exploration
status: open
summary: "Whether disk and other host alerts stay set by hand in the Beszel hub, are created from Ansible, or become jobs that push to Gatus."
topic: monitoring-alerting
related: [ADR-0011, ADR-0072, ADR-0081]
---

# Where should a host-resource alert be declared so that a rebuilt monitor brings it back?

Beszel watches every app host, and an alert on a host's disk, memory or load is a
rule inside the hub. The repo records the hub's notification channel as a manual
step and records no rule, so it cannot say whether the disk of any host is watched
or at what level. The question is where such a rule should be written down, and held
to, so that it comes back with the monitor.

## What bears on it

- The hub keeps its alert configuration in its own database. Its notification
  channel is added by hand after first boot and is "not Ansible-managed"
  ([`beszel.md`](../topics/monitoring/beszel.md#alert-notifications)). That doc
  names no alert rule.
- The hub's `data` volume has a backup and a restore drill row
  ([`coverage.md`](../topics/disaster-recovery/coverage.md)), so rules in its
  database survive a restore. They are lost when the hub is deliberately wiped, a
  procedure `beszel.md` describes, and on a rebuild that does not restore the volume.
- The agent runs on every app host, `storage` included.
- [ADR 0081 (On-site archive deletion)](../decisions/0081-protecting-on-site-backup-archives-from-their-writer/revision-000.md)
  makes the free space of the backup volume a condition of recovery: a locked archive
  cannot be removed over S3 to make room. Its assumptions ask for a signal for a
  stopped worker and for room on the volume, and the first is to be named before the
  revision is approved.
- Gatus carries the lab's other "did this still happen" signals. A job pushes on
  success, silence alerts, and the threshold and the schedule are in the repo
  ([`gatus.md`](../topics/monitoring/gatus.md#pushing-from-a-job),
  [ADR 0072 (Job heartbeats)](../decisions/0072-detecting-scheduled-jobs-that-stop-running/revision-000.md)).
- The hub is built on PocketBase, and third-party tooling reads its alerts from an
  `alerts` collection through that API
  ([an example](https://glama.ai/mcp/servers/Red5d/beszel-mcp/tools/list_alerts)).
  Whether alerts can be created through it reliably, and across Beszel upgrades, is
  still to be checked.

## Options

1. **Set in the hub's UI and recorded in `beszel.md`.** The cheapest. Cost: nothing
   checks that the rules exist or still match the doc, and a wipe removes them.
2. **Created through the hub's API from Ansible.** Rules come back with the hub.
   Cost: a hub credential in the secret catalog, a role that is idempotent against
   records Beszel owns, and a dependency on an API whose stability across upgrades is
   unchecked.
3. **A check on the host that pushes to Gatus on success**, one per signal. The
   threshold lives in the repo and a Molecule scenario can test that it fires, like
   the other jobs. Cost: a script, a unit, a heartbeat id and a token for each signal,
   and it covers only what was written.
4. **Nothing beyond the one-off free-space check ADR 0081 asks for before the
   conversion.** Cost: the volume can fill afterwards with nothing to say so, except
   hub rules that may not exist.

## Leaning

Option 3 for the one signal ADR 0081 needs, since it follows a pattern the repo
already tests, and leave Beszel's own rules as they are unless a wipe or a rebuild is
shown to lose them.
