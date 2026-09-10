# CD Agent

**Status:** `Not started`

Replaces manual `ansible-playbook` deploys and rotation runs with a
dedicated, pull-based automation host. The second half of the
OpenBao+CD-agent migration this repo originally scoped together —
OpenBao itself is done; see ADRs
[0017](../decisions/0017-openbao-bootstrap-secret-split.md) through
[0026](../decisions/0026-openbao-audit-device-and-r2-per-read-watcher.md)
and the `openbao-*.md` docs for that half. This project starts now
because it depends on that foundation: the CD agent's own AppRoles
([0020](../decisions/0020-controller-single-broad-approle-not-split-by-consumer.md))
can't be scoped until OpenBao holds real credentials to build policies
against — which it now does.

## Stages

| # | Stage | Status |
| :-: | :--- | :--- |
| 1 | `cd_agent` host — dedicated LAN box, fixed IP, `preloop` pollers for deploy/maintenance/rotation/freshness | Not started |
| 2 | `cd-agent-deploy` / `cd-agent-rotation` AppRoles, CIDR-bound | Not started |
| 3 | Retire `controller`'s standing AppRole | Not started |

## Stage detail

### Stage 1 — `cd_agent` host

A dedicated LAN host, fixed IP, zero inbound ports, running
systemd-timer pollers that invoke `preloop` against GitHub
Actions-format workflow files for deploy/maintenance/rotation/
freshness jobs. `preloop`'s CLI event-flag behavior beyond bare
`pull_request` is unverified — needs a spike before this stage's
deploy/rotation jobs are built on it. See the
[draft](../decisions/drafts/pull-based-cd-agent-not-self-hosted-github-runner.md)
this stage implements.

### Stage 2 — AppRoles

Two CIDR-bound AppRoles, per the
[draft](../decisions/drafts/cd-agent-approle-policy.md):
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

- `preloop`'s CLI event-flag behavior (Stage 1) — spike needed before
  building on it.
- Which cloud credentials beyond B2/R2/OCI get rotation automation,
  and whether "rotation" means alert-only or full rotate-and-revoke,
  isn't scoped yet.
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
