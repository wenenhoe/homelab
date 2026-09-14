# NIST SP 800-53 Alignment (Selective, Not a Compliance Program)

This repo has no compliance driver, no assessor, and no ATO — nothing
here is an attestation. While designing this repo's doc governance and
access model, a handful of practices already adopted for their own
reasons turned out to closely resemble a specific NIST SP 800-53
control's intent. This page names those, honestly, in one place — it
doesn't score coverage, chase a full control baseline, or tag
individual docs with a label that then has to be kept in sync forever
(see
[`metadata-governance-system-evaluate-vs-existing.md`](decisions/drafts/metadata-governance-system-evaluate-vs-existing.md)
for why per-doc tagging was tried and rejected).

Six controls were checked against actual repo content, not assumed
from the control's title. Five had a real, specific match. One didn't
and says so below, rather than being quietly dropped.

## RA-3 — Risk Assessment

Every draft in [`decisions/drafts/`](decisions/drafts/README.md) that
depends on something unverified carries an `## Assumptions` section:
the claim, why the decision breaks if it's wrong, and how/when it gets
checked. That's RA-3's core intent — identify and evaluate risk before
committing — running as a documentation habit instead of a formal risk
register. Not every draft has one: a draft that's already settled
folds it into Context instead, and a couple of exploratory drafts use
a differently-named section — see that directory's own README for
which is which.

## CM-2 — Baseline Configuration

[ADR 0001](decisions/0001-adopt-ansible-not-manual-deployment.md) is
this, directly: every host's configuration is defined by Ansible roles
and applied idempotently, replacing manual per-host `docker compose`
over SSH. The roles themselves ([`ansible/roles/`](../ansible/roles/))
are the baseline.

## CA-7 — Continuous Monitoring

[ADR 0012](decisions/0012-backup-freshness-check-per-host.md) (per-host
backup freshness checks) and
[ADR 0026](decisions/0026-openbao-audit-device-and-r2-per-read-watcher.md)
(a per-read watcher pushing into Uptime Kuma) are both, concretely,
ongoing monitoring of a specific failure mode rather than a
point-in-time check. The
[`off-site-monitoring`](projects/off-site-monitoring.md) project — and
its
[decision draft](decisions/drafts/off-site-monitoring-independence-not-oci-tailscale-tunnel.md) —
extends this further, removing Beszel/Kuma's own single point of
failure.

## CP-9 — System Backup

[ADR 0010](decisions/0010-cloud-sync-copy-not-sync.md) (`cloud_sync`
relays encrypted backups offsite) and
[ADR 0019](decisions/0019-openbao-snapshot-push-standalone.md)
(OpenBao's own raft-snapshot push, kept standalone from the app-backup
path) are the two mechanisms that exist specifically to answer "is
there a copy of this data somewhere else."

## AC-2 / IA-2 — Account Management / Identification & Authentication

[ADR 0020](decisions/0020-controller-single-broad-approle-not-split-by-consumer.md)
and
[ADR 0025](decisions/0025-openbao-reinit-with-standing-vault-bootstrap-role.md)
are the two ADRs that actually decide how an automation identity gets
created and scoped in OpenBao (an AppRole, not a shared token). Three
drafts extend the same question to identities that don't exist yet:
[`cd-agent-approle-policy`](decisions/drafts/cd-agent-approle-policy.md),
[`openbao-client-hvac-paramiko-adoption`](decisions/drafts/openbao-client-hvac-paramiko-adoption.md),
and
[`secret-zero-bootstrap-pattern`](decisions/drafts/secret-zero-bootstrap-pattern.md)
(controller's own authentication, not just what it authenticates to).
The
[`openbao-python-client-hardening`](projects/openbao-python-client-hardening.md)
project is the build-status view for the middle one.

## CM-8 — Component Inventory: evaluated, no genuine match

`app_registry` and `host_vars` are real, and they do function as a
component inventory — but no ADR ever decided to adopt them as one;
they're existing Ansible inventory structure, documented in
[`deployment-flow.md`](deployment-flow.md) and
[`host-vars.md`](host-vars.md) as current behavior, not as a decision
record. Linking either here would be naming a topic doc as if it were
evidence of a considered control decision, which it isn't. Left
unmapped rather than stretched.

## What this page is not

Not maintained as compliance evidence, and not linked from the ADRs/
drafts/projects it references — they stay untouched, deliberately (see
the decision draft linked above for why). `check-doc-drift.py` catches
one specific staleness case mechanically: a linked ADR going
`status: superseded` fails the build until this page is reviewed (see
[`docs/ci.md#docs-drift-check`](ci.md#docs-drift-check)). It does
*not* catch a still-`accepted` ADR's reasoning changing enough to
break a mapping, or a new ADR that should be added here — both stay on
whoever's making that change, the same way most of this repo's
cross-doc currency does.
