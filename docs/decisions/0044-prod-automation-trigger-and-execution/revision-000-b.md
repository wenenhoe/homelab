---
id: ADR-0044
revision: 0
candidate: b
type: adr
title: Trigger and execution of prod-touching automation
short: CD agent trigger
solution: A private, LAN-only Gitea or Forgejo instance with Actions and a runner on the agent host
summary: How deploys and rotations that touch prod are triggered and run, without GitHub dispatching a job to a prod-reaching host.
topic: deployment-platform
status: abandoned
related: [ADR-0020, ADR-0023]
---

# Self-hosted, LAN-only Gitea Actions, not a `preloop`-poller, as the CD trigger

## Context

[`revision-000-a.md`](revision-000-a.md)
rejects any GitHub-dispatched execution model for prod-touching work,
because a public repo's dispatch model auto-runs workflows for any
contributor whose past PR was ever approved once, regardless of
current trust. That's a platform-level dispatch risk, not a
runner-isolation problem — which is why `preloop`'s own microVM
isolation didn't neutralize it either. That draft's Stage 1 design
(implemented in
[`cd-agent.md`](../../projects/cd-agent.md#stage-1--cd_agent-host))
is a systemd-timer poller invoking `preloop` CLI against workflow
files instead, specifically to avoid GitHub ever dispatching a job.

That risk is specific to a *public*, multi-contributor dispatch
surface. A private, LAN-only Gitea instance with a single write-access
account has no fork, no outside PR, and no approved-once contributor
to exploit — so a dispatch-based trigger (Gitea Actions queuing a job
on push, picked up by a registered runner) doesn't reopen that
specific hole.

Gitea's own Actions runner, `act_runner`, registers to the instance
and then polls it over an outbound-only connection to pick up queued
jobs (confirmed via Gitea's own runner docs) — no inbound port needed
on the runner host, matching the zero-inbound-ports requirement the
rejected draft already established for `cd_agent`.

**Forgejo as an alternative forge.** Forgejo is a hard fork of Gitea;
its Actions runner, `forgejo-runner`, is itself a hard fork of
`act_runner` — same design (registers to the instance, polls
outbound-only for queued jobs), but workflows live under
`.forgejo/workflows` rather than `.gitea/workflows`, and the runner
talks a Forgejo-specific ConnectRPC protocol rather than `act_runner`'s
Gitea protocol, so the two aren't drop-in interchangeable at the
instance/runner pairing even though the surrounding design is
identical. Everything in this draft's Decision and Assumptions below
applies equally to a private Forgejo instance in place of Gitea; which
of the two to actually run is a separate, still-open question — see
its own Assumptions entry below — not a reason to duplicate this
draft.

GitHub stays this repo's public canonical remote. Gitea would exist
purely as an internal, LAN-only CD trigger surface, populated by a
pull mirror of the public GitHub repo — read-only against a public
repo, so no GitHub credential needs to live on Gitea or `cd_agent`.
Gitea's pull-mirror sync is interval-based by default, not
event-driven: per Gitea's `[mirror]` config, `DEFAULT_INTERVAL = 8h`
and `MIN_INTERVAL = 10m`. A plain interval mirror at the default can't
match the rejected draft's "minutes, not hours" latency requirement;
hitting the 10-minute floor, or triggering sync on demand via Gitea's
`mirror-sync` API, would be needed instead.

## Decision

Replace Stage 1 of `cd-agent.md` with:

- A private, LAN-only Gitea **or Forgejo** instance (see Assumptions
  for how that choice gets made): no public exposure, single
  maintainer account, no outside collaborators.
- A pull mirror of the public GitHub repo, synced at `MIN_INTERVAL`'s
  10-minute floor or triggered on demand via the mirror-sync API (see
  Assumptions).
- Gitea Actions (GitHub-Actions-compatible workflow YAML) as the
  trigger and execution engine, replacing `preloop` CLI invocation
  entirely.
- `act_runner` (Gitea path) or `forgejo-runner` (Forgejo path) in
  Docker-in-Docker mode on the `cd_agent` host, registered at
  repository level, outbound-only to the instance.

Everything downstream of "a job is running" is unchanged: the same
OpenBao AppRole design
([`../0020-automation-identity-and-access-scope/revision-001.md`](../0020-automation-identity-and-access-scope/revision-001.md)), the same
self-run provisioning guard, the same not-yet-split SSH key.

## Assumptions

Never checked, because this candidate was abandoned:

- `act_runner`'s DinD mode isolates jobs and still reaches `managed_hosts` over the LAN and SSH with no extra host networking.
- A private Gitea instance with one write-access account has no dispatch-trigger risk like GitHub's approved-once contributor; a second account or outside collaborator would reopen it.
- Mirror-sync latency can meet the "minutes, not hours" requirement through `MIN_INTERVAL`'s 10-minute floor or an on-demand `mirror-sync` call from `cd_agent`'s own interval loop, without an inbound webhook.
- Forgejo's pull-mirror keys and defaults match Gitea's, so the Gitea-versus-Forgejo choice turns on governance, maturity and operability, not on this design.

## Consequences

- Gitea becomes a new always-on LAN service — web UI, admin panel, its
  own database, its own patch/backup cadence — a materially larger
  attack surface and maintenance burden than a headless poller script
  with no listening ports and no UI. That's the trade being made for
  not maintaining a bespoke `preloop`-CLI trigger integration.
- Removes `cd-agent.md`'s open item on `preloop`'s CLI event-flag
  behavior — Gitea Actions' native event handling replaces it, so that
  spike is no longer needed.
- Does not change Stages 2–3 (`0020-automation-identity-and-access-scope/revision-001.md`) or the
  SSH-key-separation open item; those proceed independently of trigger
  mechanism.
- This draft's title still says "Gitea" because that's the
  originally-evaluated case; treat it as shorthand for "a private,
  self-hosted, GitHub-Actions-compatible forge" until the Gitea-vs-
  Forgejo Assumption above resolves and this gets renamed or split
  accordingly — don't read the title as having already ruled out
  Forgejo.
- If the mirror-sync latency assumption fails and a webhook becomes
  necessary, "zero inbound ports" is lost for the mirror-trigger path
  specifically (not for `cd_agent`'s other traffic) — worth weighing
  against accepting the mirror's default polling latency for
  non-urgent jobs (rotation/freshness) and reserving a faster path
  only for deploys, if this gap materializes.
