---
id: ADR-0108
revision: 0
type: adr
title: Which images a deploy runs and where they come from
short: Images a deploy runs
solution: Every image reference carries its digest, Renovate moves the digest in a reviewed pull request, a deploy pulls an image only when it is absent from the host, and an image moves from Docker Hub to GHCR only for a gain shown for that image
summary: How a deploy is made to run exactly the container images its commit names, so an image changes only in a pull request that says so, and how the registry an image is pulled from is chosen.
topic: deployment-platform
status: accepted
related: [ADR-0004, ADR-0071, ADR-0076, ADR-0107]
former_ids: [ADR-0083, ADR-0085]
---

# 0108. Which images a deploy runs and where they come from

## Problem

A deploy of a commit that does not touch an image's line can still change which image a
host runs. The compose files name images by tag, a tag is a name its publisher can point at a
new image whenever it likes, and the deploy pulls every image before it brings a stack up.
Two deploys of the same commit can therefore run different images, and the first the
maintainer hears of a new image is a notification sent after the fact.

Most images the repository deploys come from GHCR and the rest from Docker Hub. A move between
them touches every place a reference is written, and a publisher that pushes to both makes
the choice look free. Two reasons for moving were in circulation, a changelog link Renovate can
derive and a statement that the digest is the publisher's, and neither had been checked image
by image.

What has to be true: the image a host runs is a function of the commit deployed, an image
changes only in a pull request that shows the change, and the maintainer is told of a new image
by that pull request rather than by a separate monitor. Each image's registry is chosen for a
property it gains there, the property is shown for that image, and an image stays where it is
when nothing is shown.

## Decision

- **Every reference is pinned.** Each image reference the repository deploys or runs in CI is
  written `name:tag@sha256:digest`: compose files, Dockerfile `FROM` lines, Ansible variables,
  Molecule image files and the pins in scripts and units. The tag stays for people and for
  Renovate's version comparison; the digest decides what runs.
- **Renovate maintains the pins.** `docker:pinDigests` makes it open one pull request that pins
  everything, and then a pull request that moves a digest when a tag is rebuilt or a version
  changes. Every custom regex manager for a docker image reads and writes the digest. Pin and
  digest-refresh pull requests are grouped, run in the existing Monday and Thursday window, and
  are never automerged, because the first digest is the registry's at that moment, not
  necessarily what a host is running.
- **A deploy pulls only what is absent.** Both compose pull tasks use `policy: missing`. A
  reference that changes in a pull request is a new reference and is pulled; one that does not
  change is never replaced. This needs Docker Compose 2.22 or later on every host, which the
  role asserts before pulling.
- **Self-built images are pinned too.** A consumer of `ghcr.io/wenenhoe/*` pins the digest of
  the published image, and the scheduled same-tag rebuild reaches hosts as a Renovate
  digest-refresh pull request like any other. `ci.images.registry` reads the tag from a pinned
  reference and ignores the digest. The CI boot test builds a changed Dockerfile under the tag
  alone and removes the digest from its deployed copy of the compose file, so the stack runs the
  local build.
- **An unpinned reference is a recorded exception.** A reference that has to float is listed in
  a committed allowlist with its reason, and a check fails any other reference without a digest.
- **`diun` is retired.** A digest-refresh pull request tells the maintainer about a changed image
  before a host takes it, which was `diun`'s one job. Its container, its Docker API proxy, its
  volume and its secrets are removed.
- **The weekly tag check follows the pin.** `check-image-tags` asks the registry for the digest a
  reference pins, so a registry that deleted it fails the run even if the tag still resolves. The
  image inventory it prints keeps `ref` free of the digest and lists the digests beside it.
- **Provenance is decided separately.** Whether a digest is shown to be the publisher's is
  [ADR 0107](../0107-knowing-a-pinned-artifact-is-the-publishers/revision-000.md), and it is not a
  precondition for pinning.
- **A registry move needs a gain, shown for that image.** An image moves from Docker Hub to GHCR
  only when reading both registries shows that the GHCR copy has a statement ADR 0107 can verify
  and the Hub copy lacks, or a source label that a `sourceUrl` rule is shown not to supply, and
  that the two copies are one build or the GHCR copy is the one the publisher's statement covers.
- **No image moves now.** Each Hub image stays.
- **A statement shown for the Hub copy is as good as one for GHCR.** Provenance is not a reason to
  move an image whose Hub copy is signed or attested.
- **The repository's own images stay on GHCR.** They are built and pushed by its workflows and
  attested there.
- **A new image is pulled from the registry its publisher runs and signs on,** and from Docker Hub
  only when that is the only one, or the publisher's statement covers it there.

## Alternatives considered

- **Tags only, with a monitor that reports a changed image after the fact.** The earlier position,
  and `diun` was that monitor. It tells the maintainer once a host may already have taken the image.
- **Pull always, pinned by the compose file's tag.** Two deploys of one commit can differ.
- **Move images to GHCR for a changelog link or for provenance without checking each image.** Neither
  reason held up image by image, so the rule requires the gain to be shown.

## Consequences

- Every host needs Docker Compose 2.22 or later, which the role asserts.
- A digest-refresh pull request is how the maintainer learns of a changed image, and a publisher that
  rebuilds a tag often produces noise.
- The pins are grouped and not automerged, so the first digest is reviewed.
- Self-built images take part in the same flow as any other image.

## Invariants

- A reference the repository deploys is either pinned to a digest or listed as an exception with a
  reason.
- A deploy never replaces an image that is already present under the reference the commit names.
- An image on a host changes only in a merged pull request that changes its reference.
- The tag in a pinned reference is the version a person reads; no check reads meaning from a digest.
- An image's registry is the one its reference names, and a pinned digest is the one that registry
  serves for that reference.
- A move between registries is a reviewed pull request that shows what the image gains.

## Non-goals

- Signatures, attestations or provenance for container images, and any claim that a digest is the
  publisher's ([ADR 0107](../0107-knowing-a-pinned-artifact-is-the-publishers/revision-000.md)).
- Rate limits, pull quotas or availability of either registry.
- Vulnerability assessment of the images
  ([ADR 0071](../0071-assessing-the-vulnerabilities-of-deployed-container-images/revision-000.md)),
  which keeps reading the inventory's `ref`.
- Moving Renovate to its own branch
  ([ADR 0076](../0076-keeping-what-production-runs-apart-from-work-in-progress/revision-000.md)).

## Reconsideration triggers

- Renovate stops reading or writing a digest for a regex manager.
- A publisher whose images the repository runs rebuilds a tag often enough that refresh pull requests
  are noise.
- Image signatures or attestations become a basis for accepting a digest.
- A publisher of a Hub image begins to push to GHCR, or signs differently on one registry than on the
  other, or a Hub image's label changes so that Renovate's link for it changes.
- ADR 0107's registry shows a Hub image as *unsigned* where a GHCR copy of it is not.
