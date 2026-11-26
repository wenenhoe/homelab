# NIST SP 800-53 Alignment (Selective, Not a Compliance Program)

This repo has no compliance driver, no assessor, and no ATO — nothing
here is an attestation. While designing this repo's doc governance and
access model, a handful of practices already adopted for their own
reasons turned out to closely resemble a specific NIST SP 800-53
control's intent. This page names those, honestly, in one place — it
doesn't score coverage, chase a full control baseline, or tag
individual docs with a label that then has to be kept in sync forever
(see
[ADR 0028 (Doc metadata)](../../../decisions/0028-doc-metadata-and-governance/revision-000.md)
for why per-doc tagging was tried and rejected).

Seven controls were checked against actual repo content, not assumed
from the control's title, and each section below says what the match
covers. A control with no decision behind it stays unmapped and says so,
rather than being quietly dropped.

## RA-3 — Risk Assessment

Every `working` decision revision that depends on something unverified
carries an `## Assumptions` section: the claim, why the decision
breaks if it's wrong, and how/when it gets checked. That's RA-3's core
intent — identify and evaluate risk before committing — running as a
documentation habit instead of a formal risk register. A revision
can't be `approved` while any entry remains; a resolved one folds into
Context and is deleted (see
[`docs/decisions/README.md#assumptions`](../../../decisions/README.md#assumptions)).

## RA-5 — Vulnerability Monitoring and Scanning

[ADR 0071 (Image vulnerability assessment)](../../../decisions/0071-assessing-the-vulnerabilities-of-deployed-container-images/revision-000.md)
decides a weekly scan of every deployed container image, ranked by how
reachable each image is and what its compromise would grant. That is
RA-5's intent — monitor for vulnerabilities on a defined schedule,
analyze what the scans find, and remediate by risk — in the places this
repo can act. The scan is checked against the repo's own image inventory,
so a gap in coverage is visible; each run records how fresh the
vulnerability database it used was; and each fixable finding is tracked
from its first sighting, so the time to remediate is measurable against
a target set per priority band. See
[`security-scanning.md`](security-scanning.md#image-vulnerability-assessment).

What it isn't: it covers container images only, not host operating
systems; the remediation targets are measured, not enforced; and a fixed
package version doesn't mean a published image carries the fix.

## CM-2 — Baseline Configuration

[ADR 0001 (Host config from repo)](../../../decisions/0001-host-configuration-reproducible-from-repo/revision-000.md) is
this, directly: every host's configuration is defined by Ansible roles
and applied idempotently, replacing manual per-host `docker compose`
over SSH. The roles themselves ([`ansible/roles/`](../../../../ansible/roles))
are the baseline.

## CA-7 — Continuous Monitoring

[ADR 0012 (Backup verification)](../../../decisions/0012-verifying-backups-actually-land/revision-000.md) (per-host
backup freshness checks) and
[ADR 0026 (High-value secret read alerts)](../../../decisions/0026-detecting-reads-of-high-value-secrets/revision-001.md)
(a per-read watcher pushing a heartbeat to Gatus) are both, concretely,
ongoing monitoring of a specific failure mode rather than a
point-in-time check. The
[`off-site-monitoring`](../../../projects/off-site-monitoring.md) project — and
its
[working decision](../../../decisions/0049-monitoring-that-survives-loss-of-the-site/revision-000.md) —
extends this further, removing Beszel and Gatus's own single point of
failure.

## CP-9 — System Backup

[ADR 0010 (Offsite copy deletion)](../../../decisions/0010-preventing-homelab-side-deletion-of-offsite-copies/revision-000.md) (`cloud_sync`
relays encrypted backups offsite) and
[ADR 0111 (Secrets store recovery)](../../../decisions/0111-recovering-the-secrets-store-from-total-loss/revision-000.md)
(OpenBao's own raft-snapshot push, kept standalone from the app-backup
path) are the two mechanisms that exist specifically to answer "is
there a copy of this data somewhere else."

## AC-2 / IA-2 — Account Management / Identification & Authentication

[ADR 0020 (Automation identity scope)](../../../decisions/0020-automation-identity-and-access-scope/revision-000.md)
and
[ADR 0025 (Admin without root token)](../../../decisions/0025-admin-capability-without-a-standing-root-token/revision-000.md)
are the two ADRs that actually decide how an automation identity gets
created and scoped in OpenBao (an AppRole, not a shared token). Two
working revisions extend the same question to identities that don't
exist yet:
[ADR 0020 revision 001 (Automation identity scope)](../../../decisions/0020-automation-identity-and-access-scope/revision-001.md)
and
[ADR 0047 (First-credential bootstrap)](../../../decisions/0047-first-credential-bootstrap-for-automated-processes/revision-000.md)
(controller's own authentication, not just what it authenticates to).

## CM-8 — System Component Inventory

[ADR 0121 (Component inventory)](../../../decisions/0121-knowing-what-components-the-lab-is-made-of/revision-000.md)
makes the repo's own declarations the inventory: hosts in
[`inventory.yaml`](../../../../ansible/inventory/inventory.yaml), the apps each
host runs in its `host_vars`, and what does not vary by host once in
[`app_catalog.yaml`](../../../../ansible/inventory/group_vars/all/app_catalog.yaml).
That is CM-8's intent for those two kinds of component: one list that is also
what gets deployed, and a check on every pull request that no listed app is
missing its entry. The record was written after the structure was in use.

What it isn't: it records what is declared, not what is observed on a host; it
leaves out host packages, the units and containers a role installs, and anything
the two lists don't name; and its only review is the check on each change.

## What this page is not

Not maintained as compliance evidence, and not linked from the ADRs
and projects it references — they stay untouched, deliberately (see
ADR 0028 linked above for why). `check_doc_drift.py` catches
one specific staleness case mechanically: a linked ADR going
`status: superseded` fails the build until this page is reviewed (see
[`docs/topics/documentation/doc-checks.md#docs-drift-check`](../../documentation/doc-checks.md#docs-drift-check)). It does
*not* catch a still-`accepted` ADR's reasoning changing enough to
break a mapping, or a new ADR that should be added here — both stay on
whoever's making that change, the same way most of this repo's
cross-doc currency does.
