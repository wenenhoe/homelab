---
id: ADR-0085
revision: 0
type: adr
title: Choosing the registry an image is pulled from
short: Image registry choice
solution: An image moves from Docker Hub to GHCR only when the move gives it a verifiable statement or a source label that its Hub copy lacks and configuration cannot supply, shown by reading both registries for that image, and none moves until that is shown
summary: Which registry each deployed image is pulled from, so a move between Docker Hub and GHCR is made for something the image gains.
topic: deployment-platform
status: working
related: [ADR-0083, ADR-0084]
---

# 0085. Choosing the registry an image is pulled from

## Problem

Most images the repository deploys come from GHCR, and the rest from Docker Hub. A move between them touches every place a reference is written, and a publisher that pushes to both makes the choice look free. Two reasons for moving are in circulation, a changelog link Renovate can derive and a statement that the digest is the publisher's, and neither has been checked image by image.

What has to be true: each image's registry is chosen for a property it gains there, the property is shown for that image, and an image stays where it is when nothing is shown.

## Context

- **Where images come from.** The images pulled from Docker Hub are `alpine`, `busybox`, `caddy` (and its `builder` tag), `amazon/aws-cli`, `curlimages/curl`, `louislam/uptime-kuma`, `openbao/openbao`, `quxfoo/wastebin`, `rclone/rclone`, `smallstep/step-ca`, `smallstep/step-cli` and `ubuntu/bind9`. The rest are on GHCR, among them the repository's own `ghcr.io/wenenhoe/*`.
- **The changelog reason.** Renovate builds a changelog link from the image's `org.opencontainers.image.source` label. `.github/renovate.json5` already sets `sourceUrl` for `ubuntu/bind9`, `quxfoo/wastebin`, `amazon/aws-cli` and `caddy`, which have no usable label, so a missing label on those is already covered by configuration. The same file carries rules for `certbot/dns-digitalocean` and `louislam/dockge`, which no image reference in the tree matches.
- **The provenance reason.** [ADR 0084 (Image digest provenance)](../0084-knowing-a-pinned-image-digest-is-the-publishers/revision-000.md) records what each publisher's workflow offers. A publisher that pushes one build to several registries and signs each tag at that digest gives every registry the same digest and the same signer, so the registry does not change what can be verified. Where the statement is verifiable, it follows the publisher's identity, and only for a publisher that signs differently per registry does the registry matter. One release each of `openbao/openbao`, `louislam/uptime-kuma`, `rclone/rclone` and `curlimages/curl` has the same digest on Docker Hub and on GHCR.
- **What a move costs.** The reference changes in each file that names it: compose files, Dockerfiles, Ansible variables, Molecule image files and the scripts and units that pin one, along with the Renovate manager that reads it. Where the digest is the same on both registries the pin carries over. Where it is not, the first pin on the new registry is a reviewed change like any other ([ADR 0083 (Images a deploy runs)](../0083-making-a-deploy-run-the-images-its-commit-names/revision-000.md)).
- **Whether a GHCR copy exists.** Read from each publisher's own workflow files, not from a registry, which this environment cannot reach:

  | Image | Publisher's workflow pushes | Outcome |
  | :--- | :--- | :--- |
  | `openbao/openbao` | `docker.io`, `ghcr.io` and `quay.io` from one build, each tag signed at that digest; the build sets the source label | Stay. The Hub copy has the same digest and the same signature, and the label is set. |
  | `smallstep/step-ca`, `smallstep/step-cli` | Docker Hub only, signed with cosign | Stay. There is no GHCR copy to move to. |
  | `rclone/rclone` | `ghcr.io` as well as Docker Hub, with `provenance: false` and no attestation | Stay. The two registries serve one digest for 1.75, and a GHCR copy would carry no statement the Hub copy lacks. Whether the Hub image's source label is set was not read. |
  | `ubuntu/bind9` | Canonical's public `bind9-rock` workflow uploads to `ghcr.io/canonical/bind9-rock`, and its `ci.yaml` names no other registry, so the Hub image is published by a process outside that repository; `9.20-26.04_edge` there is a different digest from the Hub `9.20-26.04_stable`, and the other candidate tags do not exist | Stay. The GHCR tag that exists is a different image, the Hub copy has no statement, and the changelog is already supplied by configuration. |
  | `curlimages/curl` | `docker.io` and `ghcr.io/curl/curl-container/curl-multi`, each signed with the publisher's key | Stay. The two registries serve one digest for 8.23.0, and it verifies against the publisher's key on both. |
  | `louislam/uptime-kuma` | `docker.io` and `ghcr.io` from one `docker buildx build --push` per image, which tags the build for both; no signing or attestation step | Stay. The same digest is on both registries and the Hub copy has no signature or attestation. Whether the Hub image's source label is set was not read. |
  | `quxfoo/wastebin` | None found: the source repository's workflows build no image, and its README names this Hub image | Stay. |
  | `amazon/aws-cli` | None found: the source repository's workflows build no image | Stay. |
  | `alpine`, `busybox`, `caddy` | Docker Official Images on Docker Hub; no other registry found | Stay. |

## Decision

- **A move needs a gain, shown for that image.** An image moves from Docker Hub to GHCR only when reading both registries shows that the GHCR copy has a statement ADR 0084 can verify and the Hub copy lacks, or a source label that a `sourceUrl` rule is shown not to supply, and that the two copies are one build or the GHCR copy is the one the publisher's statement covers.
- **No image moves now.** The table above is the outcome: each Hub image stays.
- **A statement shown for the Hub copy is as good as one for GHCR.** Provenance is not a reason to move an image whose Hub copy is signed or attested.
- **The repository's own images stay on GHCR.** They are built and pushed by its workflows and are attested there ([ADR 0084](../0084-knowing-a-pinned-image-digest-is-the-publishers/revision-000.md)).
- **A new image is pulled from the registry its publisher runs and signs on,** and from Docker Hub only when that is the only one, or the publisher's statement covers it there.

## Alternatives considered

- **Move every Hub image whose publisher also pushes to GHCR.** A change in every file that names the image for no property gained, repeated for every image.
- **Move everything off Docker Hub.** Several images have no GHCR copy, and the ones that do are not shown to be the same build.
- **Mirror the images to a registry of the repository's own.** A registry to run and keep current, answering a risk a pinned digest already narrows to a reviewed pull request.
- **Leave the choice to Renovate's changelog output.** It reads a label; a registry with a better-looking changelog is not a registry with a better image.

## Assumptions

- **Claim:** The Hub images in the table have no source label only where a `sourceUrl` rule exists.
  **Breaks if wrong:** An image has no changelog link, and the reason to move it becomes real.
  **Checked by:** The spike's second round, which reads each pinned Docker Hub image's labels from its digest.

## Consequences

- No reference changes, and the table records why a Hub image is where it is, so a later publisher change shows up as a reason to revisit one row.
- Docker Hub stays a dependency of the deploy and of the weekly tag check for the images listed.
- The two Renovate rules that match nothing in the tree are a separate cleanup, not part of this decision.

## Invariants

- An image's registry is the one its reference names, and a pinned digest is the one that registry serves for that reference.
- A move between registries is a reviewed pull request that shows what the image gains.

## Non-goals

- Whether a digest is the publisher's ([ADR 0084](../0084-knowing-a-pinned-image-digest-is-the-publishers/revision-000.md)).
- Rate limits, pull quotas or availability of either registry.
- Vulnerability assessment of the images ([ADR 0071 (Image vulnerability assessment)](../0071-assessing-the-vulnerabilities-of-deployed-container-images/revision-000.md)).

## Reconsideration triggers

- A publisher of a Hub image begins to push to GHCR, or signs differently on one registry than on the other.
- A Hub image's label changes, so that Renovate's link for it changes.
- ADR 0084 is accepted and its registry shows a Hub image as *unsigned* where a GHCR copy of it is not.
