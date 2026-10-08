---
id: ADR-0071
revision: 0
type: adr
title: "Assessing the vulnerabilities of deployed container images"
short: Image vulnerability assessment
solution: "A scheduled scan run from homelab-security's own CI over the images this repo deploys, ranked by reachability and consequence, with every result kept in the private tracker"
summary: "How known vulnerabilities in deployed images are found, ranked and tracked without publishing them, given most are upstream's to fix."
topic: security-hardening
status: approved
related: [ADR-0038, ADR-0045, ADR-0049, ADR-0060, ADR-0061]
---

# 0071. Assessing the vulnerabilities of deployed container images

## Problem

The images this repo deploys carry known vulnerabilities, and they change without any commit here: a database update or an upstream rebuild is enough. Three things have to be possible. Find which known vulnerabilities affect which deployed image. Rank them by what an attacker could do with them in this lab. See whether the position is improving. None of it may leave a record on a surface this repo's history, pull requests or Actions logs expose.

## Context

**Why a first attempt was dropped.** Image CVE scanning in this repo's CI, in several scopes and with an issue dashboard on top, was removed because most findings were third-party images waiting on an upstream rebuild, which nothing here can act on ([`security-scanning.md`](../../topics/engineering/security-scanning.md#why-no-image-cve-scanning)). That verdict was reached over a subset: the scan listed images with a `compose*.yaml` glob, which skips every templated compose file, and it ignored images pinned in Ansible variables and scripts. The conclusion is worth testing again over a complete inventory rather than assuming.

**Where results can live.** A scan result names an image, a fixable vulnerability and, once ranked, how reachable that image is. That is the content [`docs/README.md#public-repo`](../../README.md#public-repo) keeps out of git history, and Actions logs on a public repository are public as well ([ADR 0060](../0060-tracking-and-managing-code-review-findings-for-a-public-repository/revision-000.md), [ADR 0061](../0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md)). The run therefore has to be defined in, and triggered from, `homelab-security`, which reads this repo by a plain clone.

**An inventory already exists.** [`tools/ci/images/remote.py`](../../../tools/ci/images/remote.py) collects every image reference the repo pins, wherever it pins it: `image:` lines in compose files and Ansible, `FROM` lines, and each Renovate `docker` custom manager's target. Each reference comes with the files that name it, which is enough to tell a deployed image from a Dockerfile base or a Molecule or CI image.

**What the tools provide.** Trivy's JSON gives each image a created date (`Metadata.ImageConfig.created`) and a digest (`Metadata.RepoDigests`), and each finding a `Status`, a `FixedVersion` (empty when the package has none) and a `CVSS` map. Some findings carry no CVSS vector, and a few distroless or static images report no OS. `trivy version --format json` gives the vulnerability database's `UpdatedAt`, `NextUpdate` and `DownloadedAt`, and the Java database's. The CISA known-exploited feed is one anonymous JSON file under 2 MB. The EPSS API takes 100 CVEs per call and returns scores as strings; a small share of CVEs have none, which means unknown, not zero. A package having a fixed version says nothing about whether any published image carries it.

**What a run costs.** From a two-CPU hosted runner, anonymously and with no registry credential, a cold scan of all the deployed images took about two minutes: roughly 15 seconds to install Trivy, fetch the database and scan the first image, and 100 seconds for the rest. That covers the images this repo publishes and the Docker Hub ones, whose anonymous-pull counter did not move. Afterwards Trivy's cache directory held the vulnerability database (about 1.4 GB), the Java database (about 1.5 GB) and under 10 MB of layer analysis for every image together. Upstream replaces the database daily, so a copy kept from the previous week is stale on arrival. The tracker's `main` carries no branch protection, and its built-in token, with contents and pull-request write, can push a branch, open a pull request and merge it.

**Threat model.** The adversary already holds a foothold inside the network: a LAN or tailnet peer such as a lost device or a compromised node, including the off-site monitoring host [ADR 0049](../0049-monitoring-that-survives-loss-of-the-site/revision-000.md) plans, or a stolen application credential. The open internet is not the baseline: the reverse proxy is reachable over the LAN and the tailnet only. The asset is the lab's hosts and what they hold. The attack path runs from the foothold to a route that skips the forward-auth check, or to the proxy and auth components that sit in front of every route; with a credential, to any authenticated app. A component whose compromise grants wide access (the Docker API, identity, secrets, backups) makes the same flaw worth more. A separate path, an upstream tag re-pointed at different contents, is not a CVE at all, but the digests recorded for this assessment make it visible.

**Prior art.** The design borrows ideas from NIST SP 800-53's vulnerability monitoring and flaw remediation controls: scan coverage measured against an inventory, freshness of the scanner's own data, trend analysis, remediation targets set by risk. It claims no alignment; [`nist-800-53-alignment.md`](../../topics/engineering/nist-800-53-alignment.md) is revisited only if this lands.

## Decision

- **Scope.** Every image the repo deploys, taken from the existing inventory and classified by where it is pinned. A deployed image is scanned. A Dockerfile base is covered through the image built from it. An image used only by Molecule or CI is listed and not scanned. The inventory gains a `list --json` form so the consumer depends on a tested contract and not on parsing text.
- **Where it runs.** One scheduled `homelab-security` workflow of three jobs. `inventory` holds a read-only token, clones this repo anonymously and is the only job that runs code taken from it. `scan` holds a read-only token and scans every deployed image from one job with one database fetch, taking the image from the registry only. `publish` holds the write token and consumes JSON as data, after validating every field. Image references are checked against a strict pattern before they reach a command line. Nothing from a run is cached except the pinned Trivy binary: every run scans cold.
- **What is recorded.** In the tracker, outside `findings/`: an append-only history with one line per run and image (digest, tag, created date, the vulnerability database's timestamp, scan status, counts by severity and by whether a fix exists, known-exploited count, and the classification used); the currently open fixable findings with the date each was first seen; a policy file; accepted-risk records; and a generated dashboard. The tracker's finding schema and validator are untouched, and the tracker gets its own validator for these files.
- **Ranking.** Two ordinal axes and no numeric score. *Reachability* is derived from this repo's own configuration: reachable before authentication, only after it, or not at all through the proxy. The proxy and auth components are fixed at the first level because every route passes through them. *Consequence* is maintained by hand in the policy file, three levels. Together they give three priority bands. An image the classifier cannot place ranks in the top band. A finding counts as fixable when Trivy reports a fixed package version, and the dashboard states that this does not mean a published image carries the fix. Fixable and unfixable findings are counted apart. Exploit-likelihood signals (the CISA known-exploited list and EPSS) annotate findings where available, and a missing score or CVSS vector is recorded as unknown, never as low. A host's zone, on-prem or off-site, is an attribute read from the policy file.
- **Reporting.** Counts are kept per image, and the dashboard leads with priority bands and per-image figures, never a fleet-wide raw total: an image that bundles many libraries can account for most of a raw count.
- **Accepted risk.** A record names the image and vulnerability, the reason, what would change the decision, and an expiry. The expiry is required. An expired record stops suppressing its finding.
- **Notification.** A routine run commits its results quietly. Only a defined trigger opens a pull request in the tracker, which is what notifies: a new fixable critical or any known-exploited finding in the top band, coverage under full on two consecutive runs, a vulnerability database past its `NextUpdate`, an accepted-risk record within 14 days of expiry.
- **Failure handling.** A failed scan or database refresh is recorded as a failure, never as zero findings. A database failure aborts the run before anything is committed. An inventory that shrinks sharply against the previous run aborts and notifies.

## Alternatives considered

- **Scan in this repo's CI and keep an issue dashboard** (the dropped attempt). Run logs and issues are public on this repository. Rejected on the public-repo rule alone.
- **One finding file per vulnerability in `findings/`.** The tracker's queue is for code-review findings a person triages; per-CVE files would bury it. Promoting a narrow class of results to findings can be its own decision later.
- **A matrix of one job per image.** Each job fetches the database and pulls from registries in parallel, which multiplies rate-limit exposure and per-job minute rounding for no gain at this scale. Lost to one sequential job.
- **Skip an image whose digest is unchanged.** The database moves daily, so an unchanged digest still gains findings; skipping defeats a weekly scan.
- **Cache Trivy's database between runs.** The cache directory is about 3 GB, upstream replaces the database daily, and a cold run takes about two minutes. A weekly cache entry would save part of that and cost a large entry each week. Lost to a cold scan every time.
- **A weekly PDF report sent to Telegram from the CD agent**, the idea in [`cd-agent.md`](../../projects/cd-agent.md). It needed the CD agent only to read a Telegram secret. A tracker notification needs no secret, and the CD agent does not exist yet.
- **Host package scanning in the same job.** Different data source and a different tool; see Non-goals.

## Consequences

A second job class runs from `homelab-security`'s CI, on its Actions minutes. The consequence levels are a hand-maintained file and can drift from the apps that exist; the top-band default for unclassified images makes drift loud, not silent. The reachability derivation reads this repo's app catalog and host variables, so a change to their shape appears as unclassified images, not as silence. Image results depend on upstream rebuilds this repo cannot hasten. A fixed package version does not mean a fixed image has been published, so a finding can count as fixable while no published image fixes it; the dashboard says so, and comparing against the newest published tag is a later refinement. The resulting behavior is described in [`security-scanning.md`](../../topics/engineering/security-scanning.md) once this is accepted.

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
- Whether a newer published tag already carries the fix for a finding. A fixed package version is the only fix signal.
- Misconfiguration and secret scanning, which stay as [ADR 0038](../0038-iac-misconfiguration-scanning/revision-000.md) describes.

## Validation

`list --json` has unit tests here. The tracker's validator and tests cover the policy and accepted-risk files. In operation, the dashboard's coverage figure and database age, and the notification triggers above, show when the assessment stops seeing what it should.

## Reconsideration triggers

- A route becomes reachable from the internet, or the off-site host accepts any inbound connection from it.
- This project starts accepting external pull requests ([ADR 0061](../0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md)'s trigger).
- After a quarter of complete-inventory data, most findings are ones no published image fixes, whatever Trivy's fix flag says: the noise that ended the first attempt. Comparing against the newest published tag comes before dropping the assessment.
- A host-level vulnerability pipeline is adopted and overlaps this one.
