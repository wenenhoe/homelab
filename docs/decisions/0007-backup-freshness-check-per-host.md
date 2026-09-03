# 0007. Per-host backup freshness checks, not one centralized checker

**Status:** Accepted

## Context

Something needs to verify every app's backups are actually landing in
SeaweedFS, not just that `backup_agent`'s schedule ran. A checker
centralized on `storage` was a real option: `cloud_sync` already holds
a bucket-wide read credential there, so a single checker would cost no
new privilege.

That option was rejected: a centralized checker would need cross-host
`hostvars` fact access to know what each app host is supposed to have
backed up recently — and those facts aren't populated under
`ansible-playbook deploy.yaml --limit <host>`, the partial-deploy
pattern this repo is built around elsewhere. A centralized checker
would silently stop covering hosts outside whatever `--limit` scope
last ran, with no obvious symptom until a real restore was needed.

## Decision

Run the freshness check per host instead: a `check-freshness.timer`/
`.service` (hourly, host-side, entirely outside the backup container)
on every `backup_agent` host, checking whether *every app on that
host* has a SeaweedFS object within `offsite_backup_freshness_hours`.

## Consequences

Needs no new credential — reuses each host's own already-scoped
SeaweedFS write key (read is strictly less access than that). A future
app added to an *existing* host needs zero new config for this; only a
genuinely new host running `backup_agent` needs a new
`secrets_registry.yaml` entry and `host_vars` key.

The cost: one stale app suppresses that whole host's push, and *which*
app is stale is only visible in that unit's own journal, not from
Uptime Kuma directly. See
[`uptime-kuma.md`](../uptime-kuma.md#wiring-a-job-to-its-push-monitor)
for the exit-code/push mechanics this decision produced.
