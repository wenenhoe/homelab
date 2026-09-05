# 0020. Pull-based CD agent, not a self-hosted GitHub Actions runner

**Status:** Proposed

## Context

`docs/ci.md` documents this repo's existing GitHub Actions pipeline
(`pr-checks.yml`) — GitHub-hosted runners, no prod access, nothing at
stake if a workflow is compromised beyond CI noise. The CD side this
migration exists to support is a different animal: at minimum it needs
to reach OpenBao for deploy-time secrets, and run playbooks against
`managed_hosts`.

A self-hosted GitHub Actions runner registered to this repo, gated by
`bound_claims` at the Vault auth layer, looked like the natural fit
given the existing pipeline — until the risk specific to *public*
repos surfaced: a pull request can modify the workflow file itself to
add a `pull_request` trigger, and GitHub Actions' own dispatch model
auto-runs workflows for any contributor whose past PR was ever
approved once — a property of the platform's dispatch model, not of
who's currently trusted. Confirmed against GitHub's own documentation.
Tighter runner isolation doesn't fix this on its own: a microVM-backed
self-hosted engine ([`preloop`](https://github.com/preloopdev/preloop))
was evaluated for this same prod-touching path and rejected too in its
GitHub-dispatched form, because a deploy job needs real LAN/SSH access
to `managed_hosts` — the isolation a microVM buys for pure CI
evaporates the moment the job's entire point is reaching internal
infrastructure, and `preloop`'s own docs independently confirm this
same risk (don't run fork-PR jobs on a pool sharing a host with
sensitive credentials).

A second option — `preloop` reacting to a GitHub App webhook instead
of GitHub's dispatcher, subscribed only to `push`/`workflow_dispatch`
events and never `pull_request` — would close the fork-PR vector
structurally rather than by trusting a YAML trigger block to stay
correct, since a GitHub App only receives event types it's subscribed
to at the App level, and `push`/`workflow_dispatch` are inherently
gated by real repo write access regardless (a fork's commits never
generate a `push` event upstream). It's a real, independently safe
design — but it requires exposing an inbound endpoint for webhook
delivery, narrow and HMAC-authenticated but still inbound, which
reopens the "zero inbound ports" goal this design otherwise achieves.
Rejected for that reason.

A true secretless OIDC-to-OpenBao pattern doesn't apply here either:
that requires a JWT signed by GitHub's own OIDC issuer, which only
happens for jobs GitHub itself dispatched. A self-hosted execution
engine reacting to relayed events isn't GitHub and can't produce a
token GitHub's issuer signed — and trusting a token the same engine
mints on the same box being protected would be circular.

Introducing OpenBao doesn't change any of this by itself. It's worth
doing regardless of execution mechanism (rotation, audit, no plaintext
credential sitting on disk — see
[0018](0018-openbao-repoint-not-native-plugin.md)), but a secrets
manager only matters once a job is already running; the actual
question here is what's allowed to make a job run in the first place.
Whatever authenticates to OpenBao is itself just a relocated standing
credential — the same problem one layer down, which is why the
least-privilege identity design in
[0022](0022-approle-policy-structure-two-eras.md) still matters no
matter which mechanism ends up executing the job.

## Decision

Reject anything that requires GitHub to dispatch a job, or that
requires an inbound endpoint, for prod-touching work. Use a pull-based
CD agent instead of a CD *runner*:

- A dedicated LAN host — the CD agent — distinct from both
  `managed_hosts` and `controller`, running systemd-timer pollers on a
  short interval (minutes, not hours) that fetch `origin/main` and act
  only on a new commit.
- Deploy and maintenance jobs are triggered this way; so are the
  automated credential-rotation and freshness jobs
  [0018](0018-openbao-repoint-not-native-plugin.md) introduces. Rather
  than invoking Ansible directly, the agent's poller invokes a local,
  microVM-isolated execution engine (`preloop`) against a GitHub
  Actions-format workflow file, using its direct CLI invocation path
  (e.g. `preloop run -f <workflow> --event <event>`) — the same
  mechanism already used for this repo's local pre-push CI, just
  pointed at different workflow files and events. This gets
  deploy/maintenance/rotation/freshness the same execution engine,
  isolation, and format as the existing CI pipeline, without any of it
  ever being dispatched by GitHub or requiring an inbound port.
- Zero inbound ports on the CD agent, unconditionally. Every
  interaction is outbound-only — `git fetch`, SSH out to
  `managed_hosts`, Telegram HTTPS, and OpenBao API calls. The trust
  boundary collapses to "who can push to `main`," which is already
  just the maintainer — this grants no new capability beyond what
  merging to `main` already implies.
- The CD agent's own provisioning is deliberately decoupled from the
  deploy loop and never runs as part of routine deploys — a bad commit
  that broke the agent could otherwise disable the only mechanism that
  would fix it. Provisioning includes a self-run guard comparing the
  machine identity of whatever's running the provisioning playbook
  against the CD agent's own, refusing on a match — catching an
  SSH-loopback self-provisioning attempt a hostname/IP check alone
  wouldn't.
- The same execution engine also runs this repo's existing local
  pre-push CI (re-running `pr-checks.yml` before a push) on the same
  box, with the same self-run guard, but under a separate identity
  from the CD agent's own deploy/rotation jobs — isolated so that
  local-CI execution has no path to whatever credentials those jobs
  hold. That path has no OpenBao or prod access and is out of scope
  for this ADR beyond sharing the host and guard.

## Consequences

- There's no CD platform to choose (Gitea Actions/Woodpecker/Drone/
  Jenkins/GitLab Runner never enter the picture) and no GitHub OIDC/JWT
  auth binding — AppRole is the auth binding outright, not a fallback.
- **Unverified, spike before building on it:** whether the execution
  engine's CLI event flags (equivalents of `--event push`,
  `--event schedule`, `--event workflow_dispatch`) work standalone or
  need an explicit event payload isn't confirmed for anything but the
  bare pull-request case already used for local CI. This needs a
  targeted spike, not an assumption, before the deploy/maintenance/
  rotation/freshness jobs are built on top of it. A second, distinct
  unknown even for the confirmed-working pull-request case: whether it
  carries enough payload for jobs that need a real base/head diff
  (e.g. a changed-files detection step, or a step that orders which
  hosts deploy first) to get a usable comparison, or whether those
  jobs need the event payload supplied explicitly.
- The CD agent is a third identity in OpenBao's auth model, alongside
  `controller` (the auth/policy stage) and whatever `managed_hosts`
  themselves eventually need. The auth/policy stage's "AppRole for the
  Ansible controller, one policy per secret-path family" plan assumed
  `controller` was the only automated consumer; see
  [0022](0022-approle-policy-structure-two-eras.md) for how this
  splits across `controller` and the CD agent as the migration
  progresses.
- The CD agent's inventory entry, and its real network address, are
  still placeholders pending the box's actual build. Placing the
  deploy SSH key, accepting managed-host SSH host keys, and running
  the secrets-bootstrap step on the CD box are manual, one-time steps
  by design, not automated.
- The shared SSH private key used across all managed hosts, and
  possibly the maintainer's laptop too, is one key for everything — a
  known gap, flagged but not yet acted on. Splitting a CD-agent-only
  key is a decision of its own, worth making before or during this
  stage rather than silently inherited from the current single-key
  setup.
- Which cloud credentials get rotation/freshness automation, and
  whether "rotation" means alert-only freshness checks or full
  automated rotate-and-revoke for each, isn't fully scoped yet —
  [0018](0018-openbao-repoint-not-native-plugin.md)/[0019](0019-r2-admin-token-into-openbao.md)
  cover B2/R2/OCI specifically; any other credential in
  `secrets_registry.yaml` needs the same scoping before it's assumed
  to follow the same pattern.
