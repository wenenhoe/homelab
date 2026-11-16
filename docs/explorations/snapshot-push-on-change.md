---
id: EXP-snapshot-push-on-change
title: "When should the lab push an OpenBao snapshot, if not only when someone remembers to run it?"
type: exploration
status: open
summary: "Whether a snapshot push should follow changes to the secrets store, quiet-period debounced, instead of or beside a fixed schedule, and what runs it."
topic: secrets-store
related: [ADR-0020, ADR-0026, ADR-0072, ADR-0111]
---

# The question

Today a snapshot reaches R2 and B2 only when a person runs
`snapshot-push.sh` ([`openbao-backup-restore.md`](../topics/secrets/openbao-backup-restore.md)).
The CD agent's snapshot job ([ADR 0020](../decisions/0020-automation-identity-and-access-scope/revision-001.md))
would run it unattended, but nothing yet decides *when*. A clock gives a worst
case of one interval of lost changes however quiet the store was, and pushes an
identical copy when nothing changed. Credential rotation and new secrets are
the changes that matter most after a restore: a snapshot older than a rotation
holds credentials the providers have already revoked. What would make a push
follow the change, without one push per secret when a rotation touches six?

## What bears on it

- The store is small and changes rarely, and in bursts: a rotation writes the
  new values of several credentials within minutes, then nothing for weeks.
- OpenBao's audit device writes to the container's stdout
  ([`openbao.hcl.j2`](../../docker/openbao/configs/openbao.hcl.j2)), and the
  [rotation read-watcher](../topics/secrets/openbao-rotation-read-watcher.md)
  already follows `docker logs -f openbao` on `security` and matches
  `request`-type lines by path and operation. A write should be visible the same
  way, with a different operation; the operation names a write carries in a real
  capture are still to be checked. The audit entry names the path and the
  operation; the values are hashed.
- Rotation and bootstrap code that writes secrets is in this repo
  ([`rotate-secret.yaml`](../../ansible/playbooks/rotate-secret.yaml),
  `tools/openbao_utils/`), so a writer can also announce its own change.
- The snapshot job's AppRole can save a snapshot and read six named leaf paths;
  it cannot write to the store ([ADR 0020](../decisions/0020-automation-identity-and-access-scope/revision-001.md)).
  Whatever notices a change must reach the CD agent without gaining that access.
- The `cd_agent` host is not built yet. Until it is, the push is a manual run
  from `controller`.
- A job that stops running is noticed by its heartbeat
  ([ADR 0072](../decisions/0072-detecting-scheduled-jobs-that-stop-running/revision-000.md)).
  A job that runs only on events has no interval to miss, so silence cannot be
  told from "nothing changed" without a second signal.
- The destination keeps every snapshot and the write credential cannot delete,
  so each push is a stored object. The cost of extra pushes is storage and
  noise, not loss.
- Unknown: which paths changing should count. A token renewal or a lease write
  is not a change a restore needs. The raft database itself also changes on
  every login, so a size or index comparison of the database says nothing.

## Options

**Debounced event trigger.** A change to a counted path starts a quiet-period
timer. Each further change restarts it; the push runs once the store has been
quiet for the period, and no later than a maximum wait after the first change.
Six writes within ten minutes with a thirty-minute quiet period and a two-hour
cap make one snapshot. Costs: a component that tails the audit stream and holds
the timer state, which sits next to a service that holds the whole store; the
counted-path list to maintain; and a trigger that fails silently if the tail
stops.

**Writers announce.** The rotation and bootstrap code ends with a request to
the CD agent to push, which debounces on its own side. No audit parsing and no
new component on `security`. Costs: a write made any other way (a manual
`bao kv put`, an unlisted tool) goes unannounced, so the snapshot is stale
with no sign of it.

**Time only.** The CD agent pushes on a schedule with a heartbeat, as ADR 0072
describes for other jobs. Nothing new to build. Costs: the loss window is the
interval, and a rotation just before a loss is the case it covers worst.

**Either, with a ceiling.** Either event option plus a maximum age: if no push
has happened for N days, push anyway. This bounds the silent-failure case of the
event options at N days and gives the heartbeat an interval to watch. It costs
one more schedule.

**Compare before pushing.** Whatever triggers it, the job reads a digest of the
counted paths' metadata (versions, not values) and skips the push when it
equals the last pushed digest. This removes the identical copies a ceiling would
otherwise add. It needs somewhere to keep the last digest and a read grant on
the metadata, which the snapshot role does not have.

## Leaning

An event trigger with a ceiling: debounced pushes after changes, plus a push at
least every N days, with the heartbeat on the ceiling. Which of the two event
sources is open until the counted paths are listed: if every change comes
through code in this repo, writers announcing is the smaller build; if a manual
write has to count, the audit stream is the only source that sees it. The
quiet period, maximum wait and N are numbers to choose once the CD agent's job
shape exists, and the loss the lab accepts for a rotation (none, or up to the
maximum wait) decides how short they can be.
