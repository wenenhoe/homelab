---
id: ADR-0083
revision: 0
type: adr
title: Making a deploy run the images its commit names
short: Images a deploy runs
solution: Every image reference carries its digest, Renovate moves the digest in a reviewed pull request, and a deploy pulls an image only when it is absent from the host
summary: How a deploy is made to run exactly the container images the commit names, so an image changes only in a pull request that says so.
topic: deployment-platform
status: approved
related: [ADR-0004, ADR-0071, ADR-0076, ADR-0077]
---

# 0083. Making a deploy run the images its commit names

## Problem

A deploy of a commit that does not touch an image's line can still change which image a host runs. The compose files name images by tag, a tag is a name its publisher can point at a new image whenever it likes, and the deploy pulls every image before it brings a stack up. Two deploys of the same commit can therefore run different images, and the first the maintainer hears of a new image is a notification sent after the fact.

What has to be true: the image a host runs is a function of the commit deployed, an image changes only in a pull request that shows the change, and the maintainer is told of a new image by that pull request rather than by a separate monitor.

## Context

- **How a tag moves today.** Compose files, Dockerfile `FROM` lines, Ansible variables and the pins in a few scripts name images as `name:tag`. Renovate bumps a tag when it finds a newer one. A publisher that rebuilds a tag in place (a rolling tag such as `bind9`'s or `minecraft`'s, or a patched rebuild of the same version) is invisible to it, because nothing in the repository changed.
- **How a host picks it up.** The compose role pulls with `community.docker.docker_compose_v2_pull`, whose `policy` defaults to `always`. A pull that fetches a new image under a tag the container already uses makes the next `docker_compose_v2` run with `state: present` recreate that container, so a deploy that touched nothing about the image restarts the service on a different one.
- **How the maintainer learns of it.** `diun` watches the running tags and sends a Telegram message. It reports a change after the host has already taken it, and it holds a Docker API proxy of its own ([ADR 0004 (Docker API access)](../0004-container-access-to-the-docker-api/revision-001.md)) to do it.
- **The repository's own images.** `ghcr.io/wenenhoe/*` images are rebuilt on a schedule under tags that stay the same until the Dockerfile's version changes. Today their rebuilds reach hosts only through the always-pull. If pulls stop being unconditional, a rebuild has to reach hosts some other way.
- **What a digest is.** `name:tag@sha256:...` names one image whatever the tag later points at. A runtime that is given both pulls by the digest. Renovate can maintain the pair: it adds the digest to a reference that lacks one, moves the digest when the tag is rebuilt, and moves both for a new version. Its regex managers need a `currentDigest` capture and an `autoReplaceStringTemplate` to do so; without both they read no digest and silently drop it on the next bump.
- **Trust.** A digest fixes which image is run. It does not show the image is the one its publisher meant: the digest Renovate records is whatever the registry served when it ran. Showing that is a separate question, and [ADR 0077 (Pinned checksum verification)](../0077-knowing-a-pinned-release-checksum-is-the-publishers/revision-000.md) puts container image signatures out of its scope.

**Threat model.** The adversary can replace what a tag points at, by taking a publisher's account or its registry namespace. The assets are the hosts that run the image and what the container can reach. The attack path is an unattended deploy that pulls the replaced image under an unchanged reference. Pinning removes that path for the deploy; the adversary's remaining one is a pull request that moves a digest to a malicious image, which is reviewed like any other bump.

## Decision

- **Every reference is pinned.** Each image reference the repository deploys or runs in CI is written `name:tag@sha256:digest`: compose files, Dockerfile `FROM` lines, Ansible variables, Molecule image files and the pins in scripts and units. The tag stays for people and for Renovate's version comparison; the digest decides what runs.
- **Renovate maintains the pins.** `docker:pinDigests` makes it open one pull request that pins everything, and then a pull request that moves a digest when a tag is rebuilt or a version changes. Every custom regex manager for a docker image reads and writes the digest. Pin and digest-refresh pull requests are grouped, run in the existing Monday and Thursday window, and are never automerged, because the first digest is the registry's at that moment, not necessarily what a host is running.
- **A deploy pulls only what is absent.** Both compose pull tasks use `policy: missing`. A reference that changes in a pull request is a new reference and is pulled; one that does not change is never replaced. This needs Docker Compose 2.22 or later on every host, which the role asserts before pulling.
- **Self-built images are pinned too.** A consumer of `ghcr.io/wenenhoe/*` pins the digest of the published image, and the scheduled same-tag rebuild reaches hosts as a Renovate digest-refresh pull request like any other. `ci.images.registry` reads the tag from a pinned reference and ignores the digest.
- **An unpinned reference is a recorded exception.** A reference that has to float is listed in a committed allowlist with its reason, and a check fails any other reference without a digest.
- **`diun` is retired.** A digest-refresh pull request tells the maintainer about a changed image before a host takes it, which was `diun`'s one job. Its container, its Docker API proxy, its volume and its secrets are removed.
- **The weekly tag check follows the pin.** `check-image-tags` asks the registry for the digest a reference pins, so a registry that deleted it fails the run even if the tag still resolves. The image inventory it prints keeps `ref` free of the digest and lists the digests beside it.
- **Provenance and registry choice are separate.** Whether a digest is shown to be the publisher's, and which images move from Docker Hub to GHCR, are decided in later records. Neither is a precondition for pinning.

## Alternatives considered

- **Keep `diun` and add a notification of what a deploy pulled.** The deploy would still change images on its own; the maintainer would learn of it a little sooner.
- **Pin only the rolling tags.** The fix for the visible case. A tag that is nominally immutable is rebuilt too, and a rule that depends on which tags a publisher keeps stable has to be rechecked every time one changes habit.
- **`policy: missing` without digests.** The deploy stops replacing images, and a rebuilt tag is then never picked up on a host that has the old image, while a freshly provisioned host gets the new one. Hosts running the same commit would differ for as long as the old image stays on one.
- **An update agent such as Watchtower.** It automates the behaviour this decision removes.
- **Mirror the images into a registry of the repository's own.** A registry to run and keep current, to defend an image against a risk a digest already covers.

## Consequences

- The first pull request touches nearly every image line, and digest-refresh pull requests keep arriving for tags their publishers rebuild. They are grouped to one a window.
- A same-tag rebuild of a self-built image reaches hosts only after that pull request is merged and deployed. The pin pull request has to be merged before the pull tasks change, or a rebuild in between would reach no host.
- A digest is not a changelog. A refresh pull request shows a changed hash, and Renovate cannot say why it changed.
- Docker Compose older than 2.22 on a host stops the deploy at the assertion rather than silently pulling.
- `diun`'s Telegram messages stop. The topic docs for notifications and the volume and secret inventories lose its entries.
- [`image-tag-check.md`](../../topics/engineering/ci/image-tag-check.md) and [`renovate.md`](../../topics/engineering/ci/renovate.md) describe the resulting behaviour.

## Invariants

- A reference the repository deploys is either pinned to a digest or listed as an exception with a reason.
- A deploy never replaces an image that is already present under the reference the commit names.
- An image on a host changes only in a merged pull request that changes its reference.
- The tag in a pinned reference is the version a person reads; no check reads meaning from a digest.

## Non-goals

- Signatures, attestations or provenance for container images, and any claim that a digest is the publisher's.
- Which registry an image comes from.
- Vulnerability assessment of the images ([ADR 0071 (Image vulnerability assessment)](../0071-assessing-the-vulnerabilities-of-deployed-container-images/revision-000.md)), which keeps reading the inventory's `ref`.
- Moving Renovate to its own branch ([ADR 0076 (Branch separation)](../0076-keeping-what-production-runs-apart-from-work-in-progress/revision-000.md)).

## Validation

- A test runs every docker regex manager of the real Renovate configuration over the real tree: each reads and writes a digest, and rewriting a matched pin changes that text and nothing else. A second test requires a manager for every Molecule image file, and a third forbids the lookaround and backreferences Renovate's regex engine rejects.
- Unit tests cover the pin checks and the inventory on digest-pinned references.
- A check fails an image reference that has no digest and no allowlist entry.
- The weekly `check-image-tags` run.

## Reconsideration triggers

- Renovate stops reading or writing a digest for a regex manager.
- A publisher whose images the repository runs rebuilds a tag often enough that refresh pull requests are noise.
- Image signatures or attestations become a basis for accepting a digest.
