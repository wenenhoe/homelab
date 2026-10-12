# Security policy

This repository is the source for a personal homelab: Ansible roles, Docker Compose stacks, and the Python tooling around them. It describes private infrastructure. It is not a hosted service, and there is nothing here to attack remotely.

## Reporting a vulnerability

Report privately through GitHub: open this repository's **Security** tab and choose **Report a vulnerability**. Please do not open a public issue or pull request for a suspected vulnerability, and do not paste a secret's value into a report. Say where it is and the maintainer will rotate it.

A useful report names the file, role or workflow, how to reproduce the problem or reason to it, and what an attacker would gain. This is a one-person project: there is no response-time commitment and no bounty, but a valid report is triaged and fixed on `main`, and the reporter is credited on request.

## Supported versions

The repository has no releases or tags. Only `main` is maintained, and a fix lands there as an ordinary commit.

## Scope

In scope:

- A flaw in the repository's own code or configuration (an Ansible role or playbook, a Compose template, the Python under `tools/`, a CI workflow) that would weaken the protections listed under [Security model](#security-model) for anyone who copies or deploys it.
- A credential, key or token committed anywhere in git history.

Out of scope:

- Vulnerabilities in third-party software or container images this repository deploys. Report those upstream.
- Testing, scanning or probing any host, address or service this repository configures. They are private; describe the concern in a report instead.
- A weakness that needs an already-compromised host, unless it crosses a boundary the [backup threat model](docs/topics/disaster-recovery/backup-threat-model.md) says holds.

## Security model

What is true on `main` today, each with the document that owns the detail:

- **Exposure.** Every app is proxied through Caddy with Tinyauth forward-auth and TLS by default. Opting out is an explicit per-route `auth: false`; there is no default-open path ([`AGENTS.md`](AGENTS.md#security-and-reliability-defaults), [`adding-an-app.md`](docs/topics/deploy/adding-an-app.md)).
- **Secrets.** Every secret is generated, stored and rotated through OpenBao. Automation authenticates with AppRoles rather than a shared token, and there is no standing root token ([`openbao.md`](docs/topics/secrets/openbao.md), [ADR 0025](docs/decisions/0025-admin-capability-without-a-standing-root-token/revision-000.md)). Reads of high-value secrets raise an alert ([ADR 0026](docs/decisions/0026-detecting-reads-of-high-value-secrets/revision-000.md)).
- **Backups.** The design assumes one adversary, a compromised app host. Cloud credentials never touch an app host, each host's storage identity is scoped to its own prefix, and the offsite copy is relayed with `rclone copy`, never `sync`, so nothing on-prem can delete it ([`backup-threat-model.md`](docs/topics/disaster-recovery/backup-threat-model.md), [ADR 0010](docs/decisions/0010-preventing-homelab-side-deletion-of-offsite-copies/revision-000.md)).
- **Supply chain.** Every commit in a pull request is scanned for secrets with gitleaks, and that check blocks the merge. Third-party GitHub Actions are pinned to commit SHAs, workflows are linted with actionlint and zizmor, and each pinned release download is checked against the publisher's own signature, attestation or listing ([`security-scanning.md`](docs/topics/engineering/security-scanning.md), [`release-checksum-check.md`](docs/topics/engineering/ci/release-checksum-check.md)).
- **Host hardening.** Unattended security updates are the only area of the hardening baseline applied so far; the wider baseline is decided in [ADR 0043](docs/decisions/0043-host-os-hardening-baseline/revision-000.md) and added one area at a time ([`host-hardening.md`](docs/topics/infra/host-hardening.md)).
- **Review.** Code-review findings and the container image vulnerability assessment are kept in a private repository, never here ([`security-findings.md`](docs/topics/engineering/security-findings.md), [`docs/README.md`](docs/README.md#public-repo)).

## What this repository does not claim

- It is not a compliance program. [`nist-800-53-alignment.md`](docs/topics/engineering/nist-800-53-alignment.md) names the controls its practices resemble and the one it checked and left unmapped.
- Trivy's Ansible misconfiguration and secret scans are report-only. Container images are assessed for vulnerabilities, but host operating-system packages are not.
- No intrusion detection or security-event pipeline is in place; both are still open decisions ([ADR 0039](docs/decisions/0039-intrusion-detection-scope/revision-000.md), [ADR 0045](docs/decisions/0045-security-event-collection-and-alerting/revision-000.md)).
- A compromised app host can still tamper with its own backup archives. That residual risk is accepted and stated in the threat model.
