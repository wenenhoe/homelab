# Self-hosted, LAN-only Gitea Actions, not a `preloop`-poller, as the CD trigger

**Status:** Draft

## Context

[`pull-based-cd-agent-not-self-hosted-github-runner.md`](pull-based-cd-agent-not-self-hosted-github-runner.md)
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

- A private, LAN-only Gitea instance: no public exposure, single
  maintainer account, no outside collaborators.
- A pull mirror of the public GitHub repo, synced at `MIN_INTERVAL`'s
  10-minute floor or triggered on demand via the mirror-sync API (see
  Assumptions).
- Gitea Actions (GitHub-Actions-compatible workflow YAML) as the
  trigger and execution engine, replacing `preloop` CLI invocation
  entirely.
- `act_runner` in Docker-in-Docker mode on the `cd_agent` host,
  registered at repository level, outbound-only to the Gitea instance.

Everything downstream of "a job is running" is unchanged: the same
OpenBao AppRole design
([`cd-agent-approle-policy.md`](cd-agent-approle-policy.md)), the same
self-run provisioning guard, the same not-yet-split SSH key.

## Assumptions

- **Claim:** `act_runner`'s DinD mode gives job isolation, and real
  outbound LAN/SSH reachability to `managed_hosts`, without extra host
  networking configuration beyond what Docker-in-Docker sets up by
  default.
  **Breaks if wrong:** deploy/rotation jobs need direct LAN access
  this design assumes is available inside the DinD job container; if
  it isn't, either the runner mode changes (plain Docker or host mode,
  trading isolation for reachability) or extra bridging is needed.
  **Checked by:** a spike — register a DinD `act_runner` against a
  private Gitea instance, run a job that attempts SSH to a real LAN
  host, confirm it reaches it with no additional network config.
- **Claim:** a private Gitea instance with a single write-access
  account has no dispatch-trigger equivalent to GitHub's
  approved-once-contributor risk.
  **Breaks if wrong:** adding any second account or outside
  collaborator reopens the same class of risk the rejected draft
  rules out, and this decision needs revisiting before that happens,
  not after.
  **Checked by:** revisit at the point any second account is
  proposed — not spike-able now, since it depends on a future decision
  not yet made.
- **Claim:** mirror-sync latency can be brought down to match the
  rejected draft's "minutes, not hours" requirement, either via
  `MIN_INTERVAL`'s 10-minute floor or an on-demand `mirror-sync` API
  call triggered by something that already knows `main` changed.
  **Breaks if wrong:** if neither path gives acceptable latency, the
  latency requirement has to relax, or something must call
  `mirror-sync` immediately after every push — which likely means a
  GitHub webhook hitting Gitea, reintroducing an inbound-triggered
  component the rejected draft avoided for a different reason (zero
  inbound ports).
  **Checked by:** a spike — measure actual mirror-sync latency at the
  10-minute floor against a live private instance; separately confirm
  whether an on-demand `mirror-sync` call can be made by `cd_agent`'s
  own existing interval loop (staying outbound-only) instead of
  needing an inbound webhook.

## Consequences

- Gitea becomes a new always-on LAN service — web UI, admin panel, its
  own database, its own patch/backup cadence — a materially larger
  attack surface and maintenance burden than a headless poller script
  with no listening ports and no UI. That's the trade being made for
  not maintaining a bespoke `preloop`-CLI trigger integration.
- Removes `cd-agent.md`'s open item on `preloop`'s CLI event-flag
  behavior — Gitea Actions' native event handling replaces it, so that
  spike is no longer needed.
- Does not change Stages 2–3 (`cd-agent-approle-policy.md`) or the
  SSH-key-separation open item; those proceed independently of trigger
  mechanism.
- If the mirror-sync latency assumption fails and a webhook becomes
  necessary, "zero inbound ports" is lost for the mirror-trigger path
  specifically (not for `cd_agent`'s other traffic) — worth weighing
  against accepting the mirror's default polling latency for
  non-urgent jobs (rotation/freshness) and reserving a faster path
  only for deploys, if this gap materializes.
