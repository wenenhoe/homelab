---
id: ADR-0071
revision: 0
type: adr
title: "Assessing the vulnerabilities of deployed container images"
solution: "A scheduled scan run from homelab-security's own CI over the images this repo deploys, ranked by reachability and consequence, with every result kept in the private tracker"
summary: "How known vulnerabilities in deployed images are found, ranked and tracked without publishing them, given most are upstream's to fix."
topic: security-hardening
status: working
related: [ADR-0038, ADR-0045, ADR-0049, ADR-0060, ADR-0061]
---

# 0071. Assessing the vulnerabilities of deployed container images

## Problem

The images this repo deploys carry known vulnerabilities, and they change without any commit here: a database update or an upstream rebuild is enough. Three things have to be possible. Find which known vulnerabilities affect which deployed image. Rank them by what an attacker could do with them in this lab. See whether the position is improving. None of it may leave a record on a surface this repo's history, pull requests or Actions logs expose.

## Context

**Why a first attempt was dropped.** Image CVE scanning in this repo's CI, in several scopes and with an issue dashboard on top, was removed because most findings were third-party images waiting on an upstream rebuild, which nothing here can act on ([`security-scanning.md`](../../topics/engineering/security-scanning.md#why-no-image-cve-scanning)). That verdict was reached over a subset: the scan listed images with a `compose*.yaml` glob, which skips every templated compose file, and it ignored images pinned in Ansible variables and scripts. The conclusion is worth testing again over a complete inventory rather than assuming.

**Where results can live.** A scan result names an image, a fixable vulnerability and, once ranked, how reachable that image is. That is the content [`docs/README.md#public-repo`](../../README.md#public-repo) keeps out of git history, and Actions logs on a public repository are public as well ([ADR 0060](../0060-tracking-and-managing-code-review-findings-for-a-public-repository/revision-000.md), [ADR 0061](../0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md)). The run therefore has to be defined in, and triggered from, `homelab-security`, which reads this repo by a plain clone.

**An inventory already exists.** [`tools/ci/images/remote.py`](../../../tools/ci/images/remote.py) collects every image reference the repo pins, wherever it pins it: `image:` lines in compose files and Ansible, `FROM` lines, and each Renovate `docker` custom manager's target. Each reference comes with the files that name it, which is enough to tell a deployed image from a Dockerfile base or a Molecule or CI image.

**Threat model.** The adversary already holds a foothold inside the network: a LAN or tailnet peer such as a lost device or a compromised node, including the off-site monitoring host [ADR 0049](../0049-monitoring-that-survives-loss-of-the-site/revision-000.md) plans, or a stolen application credential. The open internet is not the baseline: the reverse proxy is reachable over the LAN and the tailnet only. The asset is the lab's hosts and what they hold. The attack path runs from the foothold to a route that skips the forward-auth check, or to the proxy and auth components that sit in front of every route; with a credential, to any authenticated app. A component whose compromise grants wide access (the Docker API, identity, secrets, backups) makes the same flaw worth more. A separate path, an upstream tag re-pointed at different contents, is not a CVE at all, but the digests recorded for this assessment make it visible.

**Prior art.** The design borrows ideas from NIST SP 800-53's vulnerability monitoring and flaw remediation controls: scan coverage measured against an inventory, freshness of the scanner's own data, trend analysis, remediation targets set by risk. It claims no alignment; [`nist-800-53-alignment.md`](../../topics/engineering/nist-800-53-alignment.md) is revisited only if this lands.

## Decision

- **Scope.** Every image the repo deploys, taken from the existing inventory and classified by where it is pinned. A deployed image is scanned. A Dockerfile base is covered through the image built from it. An image used only by Molecule or CI is listed and not scanned. The inventory gains a `list --json` form so the consumer depends on a tested contract and not on parsing text.
- **Where it runs.** One scheduled `homelab-security` workflow of three jobs. `inventory` holds a read-only token, clones this repo anonymously and is the only job that runs code taken from it. `scan` holds a read-only token and scans every deployed image from one job with one database fetch, taking the image from the registry only. `publish` holds the write token and consumes JSON as data, after validating every field. Image references are checked against a strict pattern before they reach a command line.
- **What is recorded.** In the tracker, outside `findings/`: an append-only history with one line per run and image (digest, tag, created date, the vulnerability database's timestamp, scan status, counts by severity and by whether a fix exists, known-exploited count, and the classification used); the currently open fixable findings with the date each was first seen; a policy file; accepted-risk records; and a generated dashboard. The tracker's finding schema and validator are untouched, and the tracker gets its own validator for these files.
- **Ranking.** Two ordinal axes and no numeric score. *Reachability* is derived from this repo's own configuration: reachable before authentication, only after it, or not at all through the proxy. The proxy and auth components are fixed at the first level because every route passes through them. *Consequence* is maintained by hand in the policy file, three levels. Together they give three priority bands. An image the classifier cannot place ranks in the top band. Fixable and unfixable findings are counted apart, and exploit-likelihood signals (the CISA known-exploited list and EPSS) annotate findings where available. A host's zone, on-prem or off-site, is an attribute read from the policy file.
- **Accepted risk.** A record names the image and vulnerability, the reason, what would change the decision, and an expiry. The expiry is required. An expired record stops suppressing its finding.
- **Notification.** A routine run commits its results quietly. Only a defined trigger opens a pull request in the tracker, which is what notifies: a new fixable critical or any known-exploited finding in the top band, coverage under full on two consecutive runs, a stale vulnerability database, an accepted-risk record within 14 days of expiry.
- **Failure handling.** A failed scan or database refresh is recorded as a failure, never as zero findings. A database failure aborts the run before anything is committed. An inventory that shrinks sharply against the previous run aborts and notifies.

## Alternatives considered

- **Scan in this repo's CI and keep an issue dashboard** (the dropped attempt). Run logs and issues are public on this repository. Rejected on the public-repo rule alone.
- **One finding file per vulnerability in `findings/`.** The tracker's queue is for code-review findings a person triages; per-CVE files would bury it. Promoting a narrow class of results to findings can be its own decision later.
- **A matrix of one job per image.** Each job fetches the database and pulls from registries in parallel, which multiplies rate-limit exposure and per-job minute rounding for no gain at this scale. Lost to one sequential job.
- **Skip an image whose digest is unchanged.** The database moves daily, so an unchanged digest still gains findings; skipping defeats a weekly scan. Only Trivy's layer cache is reused.
- **A weekly PDF report sent to Telegram from the CD agent**, the idea in [`cd-agent.md`](../../projects/cd-agent.md). It needed the CD agent only to read a Telegram secret. A tracker notification needs no secret, and the CD agent does not exist yet.
- **Host package scanning in the same job.** Different data source and a different tool; see Non-goals.

## Assumptions

- **Claim:** The pinned Trivy's JSON output, and its version output, carry the vulnerability database's update time, each image's created date, and for each finding its fixed version and CVSS vector.
  **Breaks if wrong:** The freshness and ageing measures need another source, or are dropped.
  **Checked by:** A throwaway run of the pinned Trivy against one pinned image, reading the output.
- **Claim:** The CISA known-exploited list and EPSS scores can be fetched anonymously from a runner in a stable, machine-readable form.
  **Breaks if wrong:** Ranking falls back to fix status and attack vector alone.
  **Checked by:** Fetching both from a runner in the same spike and reading their documented formats.
- **Claim:** One sequential scan of the deployed images, with Trivy's cache restored, fits the private repository's Actions minute allowance and the cache size cap, and Docker Hub's anonymous limits are not reached by the Hub-hosted images.
  **Breaks if wrong:** The workflow needs a registry credential, a cadence change, or a different split.
  **Checked by:** A cold and a warm spike run, recording elapsed time and cache size.
- **Claim:** The workflow's built-in token can commit directly to the tracker's `main` and open and merge a pull request there.
  **Breaks if wrong:** Routine results must travel by pull request, and every run would notify.
  **Checked by:** A spike commit and a spike pull request in the tracker.

## Consequences

A second job class runs from `homelab-security`'s CI, on its Actions minutes. The consequence levels are a hand-maintained file and can drift from the apps that exist; the top-band default for unclassified images makes drift loud, not silent. The reachability derivation reads this repo's app catalog and host variables, so a change to their shape appears as unclassified images, not as silence. Image results depend on upstream rebuilds this repo cannot hasten, so the dashboard separates what a fix exists for from what none does. The resulting behavior is described in [`security-scanning.md`](../../topics/engineering/security-scanning.md) once this is accepted.

## Invariants

- No credential held by this assessment can write to this repo's GitHub remote ([ADR 0061](../0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md)).
- Code taken from this repo never runs in a job that holds a write token.
- No result is written to a surface this repo's history, pull requests or Actions logs expose.
- A failed scan or a failed database refresh is never recorded as a clean result.
- An image that cannot be classified ranks in the top band.
- Every accepted-risk record has an expiry.

## Non-goals

- Host operating-system package scanning. If [ADR 0045](../0045-security-event-collection-and-alerting/revision-000.md)'s pipeline is adopted it may cover this.
- Whether what runs on a host matches what `main` declares.
- Testing whether a vulnerability is exploitable here.
- Promoting results to code-review findings.
- Per-pull-request assessment.
- Remediation itself. Tag bumps stay with Renovate and the maintainer.
- Misconfiguration and secret scanning, which stay as [ADR 0038](../0038-iac-misconfiguration-scanning/revision-000.md) describes.

## Validation

`list --json` has unit tests here. The tracker's validator and tests cover the policy and accepted-risk files. In operation, the dashboard's coverage figure and database age, and the notification triggers above, show when the assessment stops seeing what it should.

## Reconsideration triggers

- A route becomes reachable from the internet, or the off-site host accepts any inbound connection from it.
- This project starts accepting external pull requests ([ADR 0061](../0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md)'s trigger).
- After a quarter of complete-inventory data, results are still dominated by findings with no fix available, which is the noise that ended the first attempt.
- A host-level vulnerability pipeline is adopted and overlaps this one.
