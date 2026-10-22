---
id: ADR-0090
revision: 0
type: adr
title: Licences of the software the repository adopts
short: Adopted software licences
solution: The repository adopts software only under an OSI-approved licence, copyleft included, except hosted services it consumes and three named pieces of software, enforced by a check when a pin changes and a weekly check of each upstream's default-branch licence file
summary: Which licences the images, binaries, libraries, collections, hooks and actions the repository deploys or runs may carry, and how a change of licence is caught before it is adopted.
topic: repository-tooling
status: working
related: [ADR-0077, ADR-0084]
---

# 0090. Licences of the software the repository adopts

## Problem

The repository deploys images, installs release binaries, and builds on
libraries, Ansible collections, pre-commit hooks and GitHub Actions. Each one
is somebody else's software under terms that can change at the next release.
A licence moved from open source to source-available is noticed when a bump
lands, or later, unless something looks for it.

What has to be true: the licences the repository depends on are a stated
choice rather than an accident of what was convenient, an exception is
written down with its reason, and a change of licence is seen before the
version carrying it is adopted.

## Context

- **The rule is a choice, not a legal reading.** The Business Source
  License 1.1 grants production use, and its grant for Packer from 1.10.0
  names internal use as not competitive, so using Packer for the lab would
  be permitted. The reason to avoid it is that software under it cannot be
  forked and kept going if its steward changes the terms again. The
  repository already runs OpenTofu and OpenBao, the forks of two tools that
  moved to that licence.
- **A licence applies per version.** A release already pinned keeps the
  terms it shipped under. The risk is the next version Renovate proposes,
  and the earliest signal is a change to the licence file on an upstream's
  default branch, which can precede the release that carries it.
- **What the repository adopts today.** Every upstream licence file read when
  this was written is OSI-approved: permissive (Apache-2.0, MIT, BSD, the
  Unlicense), weak copyleft (MPL-2.0, LGPL-3.0) and strong copyleft (GPL-3.0,
  AGPL-3.0). tinyauth, cobalt, bentopdf and Renovate are AGPL-3.0, and lldap,
  ansible-core, hadolint and yamllint are GPL-3.0. Each is run unmodified for
  the lab's own use.
- **What a licence file does not show.** The Minecraft server that
  `itzg/minecraft-server` downloads at runtime is under Mojang's EULA, and
  the wrapper's own Apache-2.0 file says nothing about it. The CodeRabbit CLI
  is closed source. The guest operating system of the Windows virtual
  machines is proprietary. The hosted services the repository calls are
  not software it runs at all.
- **Where a licence can be read.** An image's own label is whatever its
  publisher set. The upstream source repository's licence file is the
  publisher's statement, and the repository already keeps a registry of
  every pin for the checksum check ([ADR 0077 (Pinned checksum
  verification)](../0077-knowing-a-pinned-release-checksum-is-the-publishers/revision-000.md))
  and the image provenance check ([ADR 0084 (Image digest
  provenance)](../0084-knowing-a-pinned-image-digest-is-the-publishers/revision-000.md)),
  with a test that fails when a pin has no entry.

## Decision

- **The rule.** Software the repository deploys, installs or runs in its
  tooling and CI carries an OSI-approved licence, read from the upstream
  source repository the pin comes from. Copyleft licences are allowed: the
  rule asks whether a licence is open source, not how permissive it is. A
  licence file that is not recognised counts as not approved.
- **One clause for services.** A hosted service the repository consumes
  rather than runs is outside the rule. The test is whether its code runs on
  a host the repository manages.
- **Three named software exceptions,** each with its reason, and no others:
  - the Minecraft server, which `itzg/minecraft-server` downloads under
    Mojang's EULA;
  - the CodeRabbit CLI, which is closed source;
  - the Windows guest operating system, which the desktop machines run
    because they are for using it.
- **An exception is a revision of this record.** Adding software to the list,
  or removing one, changes the policy, so it is a new revision and not an
  entry in a file.
- **Two checks keep it true.**
  - When a change touches a pin (an image tag or digest, a release checksum, a
    lock file, a provider version, a hook revision, an action), the licence
    of what it pins is compared with the registry's entry for it, and an
    entry that is missing, not OSI-approved or different from the file fails
    the check.
  - Once a week the licence file on each pinned project's upstream default
    branch is compared with the registry's entry, so a change shows up before
    the release that carries it. The weekly run sits beside the other weekly
    checks and reports through the same path.
- **A failed check holds the bump.** The pin already in place stays until the
  licence is accepted by a revision here, or the software is replaced.
- **The registry holds the evidence.** Each entry names the SPDX identifier,
  the source it was read from, and, for an exception, the reason. It extends
  the registry pattern of the checksum and provenance checks.

## Alternatives considered

- **Permissive licences only.** Rules out lldap, ansible-core, tinyauth,
  cobalt, bentopdf and Renovate, each of which is run unmodified for internal
  use, which copyleft does not restrict. It would replace working software for
  no reduction in the risk this decision answers.
- **No written rule.** The licence of a new dependency is then judged once,
  by whoever adds it, and a later relicensing is read about in a changelog or
  not at all.
- **A scan only at a fixed interval, such as quarterly.** A licence changes
  with a release, which Renovate opens as a pull request within days. A scan
  that runs later finds it after it is merged.
- **A general licence scanner over every image and package.** It reads what a
  package declares about itself, which an image label often leaves unset, and
  produces findings for software inside images that no pin names. The
  registry reads the upstream's licence file for each pin and fails when one
  is missing.
- **List each hosted service as an exception.** The list changes whenever a
  provider does and says nothing a reader could not derive from the clause.

## Assumptions

- **Claim:** `itzg/mc-backup`, `docker-compose-linter`, `croniter` and `curl`
  carry an OSI-approved licence. No licence file was found for the first
  three at the paths tried, and the curl licence is MIT-style, with its
  approval status unchecked.
  **Breaks if wrong:** each needs an entry in the exceptions list, or a
  replacement.
  **Checked by:** reading each project's licence file at its pinned version
  in the first stage of the project that builds the check.
- **Claim:** a lock file's metadata states a licence for the Python
  dependencies the repository pulls in transitively, well enough to compare
  with the rule.
  **Breaks if wrong:** the check covers direct pins only and the transitive
  set is out of its scope.
  **Checked by:** a spike reading `uv.lock` and the metadata of the
  packages it names.

## Consequences

- Packer's core, under the Business Source License from 1.10.0, fails the
  rule, so a Windows template builder is chosen among OSI-approved options.
- A new pin needs a registry entry before it merges, and a bump that changes
  a licence is held until a revision here accepts it or the software is
  replaced.
- Hosted services come and go without touching this record. Software that
  needs an exception does.
- The behaviour of the check is described in a topic doc that arrives with
  it.

## Invariants

- Every pin the repository holds has a registry entry naming its licence.
- A licence that is not recognised does not pass.
- The software exceptions are the three listed here, and a change to the list
  is a revision of this record.

## Non-goals

- A reading of what a licence obliges the repository to do.
- The licence of the repository itself, which is MIT.
- Software inside an image beyond what its pin names, and software the
  repository's operator installs on a machine for their own use.
- Whether a pinned artifact is the publisher's, which
  [ADR 0077](../0077-knowing-a-pinned-release-checksum-is-the-publishers/revision-000.md)
  and [ADR 0084](../0084-knowing-a-pinned-image-digest-is-the-publishers/revision-000.md)
  cover.
- Vulnerabilities in what is adopted.

## Validation

The two checks under Decision, and a test that fails when a pin has no
registry entry.

## Reconsideration triggers

- A tool the repository needs has no OSI-approved option and an exception
  would be its third.
- The number of named exceptions grows to the point that the rule describes
  few of the repository's dependencies.
- OSI changes how it approves licences.
