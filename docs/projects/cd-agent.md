---
id: PROJ-cd-agent
title: "CD Agent"
type: project
status: not-started
summary: "Pull-based CD agent, replacing manual deploys and `controller`'s standing AppRole."
---

# CD Agent

**Status:** `Not started`

Replaces manual `ansible-playbook` deploys and rotation runs with a
dedicated, pull-based automation host. The second half of the
OpenBao+CD-agent migration this repo originally scoped together —
OpenBao itself is done; see ADRs
[0017](../decisions/0017-recovering-the-secrets-store-from-total-loss/revision-000.md) through
[0026](../decisions/0026-detecting-reads-of-high-value-secrets/revision-000.md)
and the `openbao-*.md` docs for that half. This project starts now
because it depends on that foundation: the CD agent's own AppRoles
([0020](../decisions/0020-automation-identity-and-access-scope/revision-000.md))
can't be scoped until OpenBao holds real credentials to build policies
against — which it now does.

## Stages

| # | Stage | Status |
| :-: | :--- | :--- |
| 1 | `cd_agent` host — dedicated LAN box, fixed IP, `preloop` pollers for deploy/maintenance/rotation/freshness/security-reporting | Not started |
| 2 | `cd-agent-deploy` / `cd-agent-rotation` AppRoles, CIDR-bound | Not started |
| 3 | Retire `controller`'s standing AppRole | Not started |

## Stage detail

### Stage 1 — `cd_agent` host

A dedicated LAN host, fixed IP, zero inbound ports, running
systemd-timer pollers that invoke `preloop` against GitHub
Actions-format workflow files for deploy/maintenance/rotation/
freshness/security-reporting jobs. `preloop`'s CLI event-flag behavior beyond bare
`pull_request` is unverified — needs a spike before this stage's
deploy/rotation jobs are built on it. See the
[working decision](../decisions/0044-prod-automation-trigger-and-execution/revision-000.md)
this stage implements.

**Read before building this stage:**
[`0044-prod-automation-trigger-and-execution/revision-001.md`](../decisions/0044-prod-automation-trigger-and-execution/revision-001.md)
is a still-open, unresolved alternative that proposes replacing this
stage's mechanism entirely — a private, LAN-only Gitea *or Forgejo*
instance with an `act_runner`/`forgejo-runner`, dispatch-triggered on
push, instead of a `preloop` poller; which of Gitea or Forgejo is its
own open question inside that draft. It's a live draft, not a rejected
idea; the wording above shouldn't be read as having already decided
against it.

### Stage 2 — AppRoles

Two CIDR-bound AppRoles, per the
[working decision](../decisions/0020-automation-identity-and-access-scope/revision-001.md):
`cd-agent-deploy` (read-only on `hosts/*` and
`cloud_credentials/leaf/*`) and `cd-agent-rotation` (create/update on
both `cloud_credentials/leaf/*` and `cloud_credentials/rotation/*`) —
no shared access between the two jobs, since a compromised deploy run
shouldn't be able to reach rotation-tier credentials or vice versa.

### Stage 3 — Retire `controller`'s AppRole

Once Stages 1–2 are live and proven, delete `controller`'s Era A
AppRole outright, not narrow it. From that point `controller` holds no
standing Vault credential — any admin/debug access mints a fresh,
narrow, short-lived token on demand instead.

## Open items

- Whether Stage 1 stays a `preloop` poller or gets replaced by
  [`0044-prod-automation-trigger-and-execution/revision-001.md`](../decisions/0044-prod-automation-trigger-and-execution/revision-001.md)'s
  Gitea Actions approach — a live, unresolved fork. Resolve this
  before Stage 1 is actually built, not after.
- Stage 3's "mints a fresh, narrow, short-lived token on demand
  instead" doesn't specify how `controller` authenticates to do that
  minting once its standing AppRole is retired — see
  [`0047-first-credential-bootstrap-for-automated-processes/revision-000.md`](../decisions/0047-first-credential-bootstrap-for-automated-processes/revision-000.md)'s
  leaning answer (mTLS via step-ca, same pattern `step_ca_cert` already
  proves) and its response-wrapping answer for handing Stage 2's
  `cd_agent` AppRole `secret_id` over at provisioning time.
- `preloop`'s CLI event-flag behavior (Stage 1) — spike needed before
  building on it.
- Which cloud credentials beyond B2/R2/OCI get rotation automation,
  and whether "rotation" means alert-only or full rotate-and-revoke,
  isn't scoped yet.
- A weekly security-reporting job: Trivy image scanning, redesigned as
  a PDF report sent to Telegram (trend visibility, not a CI gate) —
  needs `cd_agent` specifically for its Telegram secret access, which
  is why this wasn't feasible from `controller`. Previous CI-integrated
  image scanning was dropped for being mostly non-actionable noise
  (third-party images awaiting upstream rebuilds) — see
  [`security-scanning.md`](../security-scanning.md#why-no-image-cve-scanning).
  This reframes the same capability as informational rather than
  actionable, which may sidestep that problem. Not scoped beyond the
  idea yet.
- The shared SSH private key across every managed host (and possibly
  the maintainer's laptop) hasn't been split into a `cd_agent`-only
  key.

## Closing checklist

Copied from
[`docs/projects/README.md`](README.md#when-a-project-finishes) — run
before deleting this doc once every stage above is Done.

- [ ] Every `Done` stage's rationale exists as a real ADR, or plainly
      didn't need one.
- [ ] Every `Done` stage's current behavior is described in a topic
      doc, not only here.
- [ ] Every open item above is resolved-and-promoted or moved to
      where it belongs next.
- [ ] Every cross-reference into this doc elsewhere in the repo is
      updated or removed.
