---
id: ADR-0091
revision: 0
type: adr
title: Where the Windows activation host's code and image come from
short: Activation host image
solution: Build a server-only image from the upstream organisation's py-kms at a tag pinned with its commit, with no web UI, database or volume, publish it from the repository's own workflow with an attestation, and remove kms-gui
summary: Whose code and whose build the Windows activation host runs, and what state and surface it carries.
topic: deployment-platform
status: working
related: [ADR-0063, ADR-0083, ADR-0084, ADR-0090]
---

# 0091. Where the Windows activation host's code and image come from

## Problem

The Windows machines activate against a KMS host that the repository runs on
`services`. Its image is somebody else's build of somebody else's fork, with a
web interface and a database volume beside it. What has to be true: the code
the host runs is a public, maintained project that can be read at the
reference the repository pins, the image is built and attested by the
repository, and the service carries no state and no surface that the protocol
does not need.

## Context

- **What is deployed.** `docker/kms/compose.yaml.j2` pins
  `ghcr.io/11notes/kms:1.0.3` and `ghcr.io/11notes/kms-gui:1.0.3` by digest.
  The server publishes `1688/tcp` on every interface. The interface sits
  behind Caddy and Tinyauth, and a `kms_data` volume holds the server's
  database; the backup stops the app to copy it.
- **Where the image's code comes from.** The image's Dockerfile clones
  `11notes/fork-py-kms` at the tag its own version names, so `1.0.3` is that
  fork's `v1.0.3`: a commit of 9 July 2025 on the fork's `next` branch. The
  fork's default branch stops at 28 May 2024. `kms-gui` adds Flask and gunicorn
  and a skin cloned from `11notes/fork-pykms-frontend`. The wrapper
  repository has newer tags of its own (`v1.5.x`) for its packaging, which are
  not the image's version.
- **The maintained line.** The original `SystemRage/py-kms` has had no
  commit since January 2021. `Py-KMS-Organization/py-kms` continues it, is
  released under the Unlicense, and carries two tags, `v1.0.0` and `v1.0.1`,
  both of 1 May 2026, with `v1.0.1` at its current head. Its database has an
  entry for Windows build 26100 (Windows 11 24H2 and Windows Server 2025)
  that the fork's `v1.0.3` lacks, and it fixed Windows Server 2019 activation
  in January 2026.
- **Provenance today.** The repository's registry records both images as
  unsigned ([ADR 0084 (Image digest provenance)](../0084-knowing-a-pinned-image-digest-is-the-publishers/revision-000.md)):
  the `kms` workflow requests an attestation and GitHub holds none for the
  pinned digest, and `kms-gui` states nothing.
- **What the server needs.** Its only third-party dependencies are `dnspython`
  and `tzlocal`; the web interface adds Flask and gunicorn. Storing client
  requests in SQLite is an option that is off unless asked for, and the only
  consumer of that table is the interface. A client's activation lives on the
  client and the server keeps no record of it.
- **How the repository builds its own images.** A `build-<name>-image.yml`
  workflow builds and attests the image, `ci.images.registry` derives its tag
  from the Dockerfile, the provenance registry lists it as attested, and a
  weekly rebuild picks up base-image patches
  ([ADR 0063 (Review image build)](../0063-what-the-code-review-image-is-built-from-and-how-it-stays-current/revision-000.md),
  [ADR 0083 (Images a deploy runs)](../0083-making-a-deploy-run-the-images-its-commit-names/revision-000.md)).

## Decision

- **Source.** The image builds `Py-KMS-Organization/py-kms` at a tag, and the
  Dockerfile pins that tag's full commit as well. The build fails if the tag
  resolves to another commit.
- **Server only.** No web UI, no SQLite option, no volume. The image installs
  `dnspython` and `tzlocal` at pinned versions and hashes, and starts the
  server directly, since the upstream entrypoint expects to start as root.
- **Built and attested by this repository.** A workflow in the pattern of the
  other image builds publishes `ghcr.io/wenenhoe/kms`, tagged with the py-kms
  version and attested, and compose pins it by digest.
- **Confined as the other containers are.** It runs as a non-root user with
  `cap_drop: ALL` and `no-new-privileges:true`, and publishes only `1688/tcp`.
- **`kms-gui` is removed,** with the `kms_data` volume, its backup entry, its
  route and its Dashy tile. Reaching the server from the client networks is
  the gateway's policy, not the compose file's.

## Alternatives considered

- **Keep the 11notes images and bump them.** There is nothing to bump to: the
  fork's latest tag is the one deployed. The code stays a 2025 snapshot on a
  side branch of the fork, and the images stay unsigned.
- **Pull an image the upstream organisation publishes.** It would still be a
  build this repository neither performs nor attests, so the unsigned entry
  would remain under another name.
- **vlmcsd.** Its last commit is from July 2023.
- **Build `kms-gui` too.** It adds a web framework and a database volume to
  back up, for a table of clients that the server records only when asked.
- **Retire the host.** The Windows machines still activate against it.

## Assumptions

- **Claim:** a current Windows 11 client activates against the image built from
  `v1.0.1`.
  **Breaks if wrong:** the tag is wrong for the clients, and the pin moves to
  a later commit or the host is reconsidered.
  **Checked by:** a Windows 11 guest running `slmgr /ato` against the built
  image on the lab network, after a run of upstream's own client against it in
  the build harness.
- **Claim:** the server runs as a non-root user with every capability dropped,
  `no-new-privileges` and a read-only root filesystem, and restarts cleanly.
  **Breaks if wrong:** the image needs a capability or a writable path, and
  this record names it.
  **Checked by:** the private `dockerd` harness, creating the container once
  and starting it twice.

## Consequences

- The activation history view goes. A request still appears in the
  container's log.
- The repository owns the rebuilds, the base image's patches and each py-kms
  bump, which Renovate proposes as a tag and its commit together.
- `kms` stops being a stateful app: its row leaves the backup table and the
  restore guide, and the old volume is removed by hand, since removing a
  volume is destructive.
- The py-kms release is one maintainer organisation's two tags, and the
  repository now depends on that line directly.
- Its licence is the Unlicense, which satisfies
  [ADR 0090 (Adopted software licences)](../0090-licences-of-adopted-software/revision-000.md).

## Invariants

- The code in the image is a public tag of the upstream project, pinned with
  its commit.
- The service writes nothing to its filesystem and publishes only its protocol
  port.
- The image is attested by this repository's workflow.

## Non-goals

- Whether and how the Windows machines are entitled to activate.
- How clients find the host (a DNS record or a setting on each client).
- Which networks may reach the host, which the gateway's policy decides
  ([ADR 0089 (OPNsense configuration)](../0089-how-the-opnsense-gateway-is-configured/revision-000.md)).
- Vulnerabilities in the base image, which the existing scans cover.

## Validation

The provenance check lists the image as attested, the image registry's pin
test holds compose to the tag the Dockerfile publishes, and a client activates
against the deployed host.

## Reconsideration triggers

- The upstream organisation stops committing, or a better maintained
  emulator appears.
- A Windows release the machines run is not covered by a tagged py-kms.
- The upstream licence changes.
