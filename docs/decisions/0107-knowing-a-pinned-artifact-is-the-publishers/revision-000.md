---
id: ADR-0107
revision: 0
type: adr
title: Knowing a pinned artifact is the publisher's
short: Pinned artifact provenance
solution: A CI check verifies each pinned release hash against the publisher's signed manifest or build attestation, and each pinned image digest against its cosign signature or GitHub attestation, with the identity fixed in the repository, and records an artifact with nothing to verify as that
summary: How a hash or digest pinned for a downloaded release binary or a container image is shown to be the one its publisher signed or attested, whoever or whatever copied it into the repository.
topic: security-hardening
status: accepted
related: [ADR-0044, ADR-0063, ADR-0064, ADR-0071, ADR-0108]
former_ids: [ADR-0077, ADR-0084]
---

# 0107. Knowing a pinned artifact is the publisher's

## Problem

Release binaries are installed on hosts and into an image under a pinned sha256,
and every image the repository deploys is pinned as `name:tag@sha256:digest`
([ADR 0108](../0108-which-images-a-deploy-runs-and-where-they-come-from/revision-000.md)).
The install stops, or the host pulls exactly that digest, if the artifact does not
match. The pin shows the artifact is the one that was pinned. It does not show the
pin is what the publisher released, because each bump copies the new hash or digest
from the place the artifact comes from: Renovate records whatever the host or
registry served when it ran. Whoever can replace a release asset, or push to a
publisher's registry namespace or the repository's own, controls both the artifact
and any statement stored beside it, and a pull request carrying both looks the same
to a reviewer as an honest one.

What has to be true: for every pinned release artifact and image, the hash or digest
is shown to be one its publisher signed or attested, where the publisher offers a
statement that can be checked, and an artifact whose publisher offers none is
recorded as that rather than assumed.

## Context

- **Release pins.** Four are checksummed downloads: the `uv` and `rclone` the CD
  agent host installs (that host holds the deploy job's credentials), the OpenBao CLI
  `.deb` installed on `security`, and the CLI zip unpacked in the review image. Each
  install verifies the file against the pin. The pin's bump copies the hash from the
  asset's own release, so nothing compares it with anything the publisher signed.
- **What publishers offer.** rclone clearsigns its `SHA256SUMS` with a long-lived
  key. OpenBao publishes `checksums.txt` with a GPG signature and Sigstore bundles.
  uv publishes a `.sha256` beside each asset and GitHub artifact attestations, and no
  detached signature. CodeRabbit publishes a `SHA256SUMS` and no signature. For images,
  the registry records per publisher whether it attests through GitHub, signs with
  cosign under a fixed workflow identity or key, or offers nothing; most offer
  nothing.
- **The repository's own images** are built by `build-*-image.yml` with
  `docker/build-push-action` and carried no attestation tying a digest to the
  workflow that built it. A BuildKit provenance or SBOM document is stored beside the
  image, so a party able to replace the image can replace it unless something signs
  it with an identity the repository fixes.
- **Tooling.** `gh attestation verify` fixes the repository an artifact must come
  from; `cosign verify` fixes a keyless identity and issuer, or a committed public
  key. `gh` comes with the runner image and `cosign` is published as a container
  image.
- **Renovate** applies a `digest` a datasource returns for a release, and maps a
  pinned hash to a new release's. Either supplies a hash or digest; neither makes it
  the publisher's.

**Threat model.** The adversary can replace a release asset and the checksum file
beside it, or push to a publisher's registry namespace or the repository's own, and
cannot sign with a publisher's offline key or make a Sigstore identity it does not hold
sign for it. The assets are the credentials and authority of the host the artifact
runs on. The attack path is a bump or digest-refresh pull request whose new pin was
derived from the tampered source.

## Decision

**The check.** A stdlib-only Python check under `tools/ci`, unit-tested
([ADR 0064](../0064-where-the-code-behind-ci-and-documentation-checks-lives/revision-000.md)),
reads a registry that holds one entry per pinned artifact. A release entry holds where
its pin lives, the file name its manifest lists, the manifest's address for the pinned
version, its tier, and for a signed artifact the signing key's fingerprint, and for an
attested one the repository that must have built it. An image entry is per image
repository and holds its tier and the identity for that tier; the check takes every
pinned digest of the repository from the tree and verifies each. The registry is the
one place a pin's tier is written down. A pinned artifact with no registry entry fails
a test.

**Release tiers.**

- *Signed*: the manifest and signature are fetched, the signature is verified with
  `gpg` in a throwaway keyring that holds only the key committed for that entry, and
  the pinned hash must equal the manifest's line for the file.
- *Attested*: the artifact is downloaded, must hash to the pinned value, and must pass
  `gh attestation verify` for the repository its entry names.
- *Listed*: a manifest with no signature; the pinned hash must equal its line, which
  catches a hash copied from the wrong place and a typo, and no more.
- *None*: the entry says the publisher gives no manifest.

**Image tiers.**

- *Attested*: must pass `gh attestation verify` for the repository its entry names.
- *Signed*: must pass `cosign verify` with the certificate identity and OIDC issuer its
  entry fixes, or, for a publisher that signs with a key, the public key committed for
  it.
- *Unsigned*: the publisher offers no statement the check can verify, and the entry says
  so. A BuildKit attestation or an SBOM that nothing ties to an identity the repository
  fixes does not lift an image out of *unsigned*.

**No key or identity is fetched.** The public key, fingerprint, repository, certificate
identity and issuer come from the entry in the repository, never from a keyserver, a web
page, the registry or the artifact being checked. A change of one is a reviewed diff. The
Sigstore trust root a verifier uses is not an entry's identity and is not covered by this.

**Self-built images are attested.** Each `build-*-image.yml` attests the digest it pushes
with `actions/attest`, with the permissions that action needs and no more, and each
`ghcr.io/wenenhoe/*` image is an *attested* entry naming this repository.

**Tools.** `gh` comes from the runner image and `cosign` runs as its version 3 container
image, pinned by digest like any other image, so no workflow installs a binary.

**When it runs.** On a pull request that changes a pinned file, a pinned image reference
or the registry, and weekly, so a manifest, key, signature or attestation that changes
upstream is noticed without a pin changing. A failure on either fails the run.

**Renovate proposes; the check decides.** A hash or digest a datasource supplies is
accepted into the pull request and trusted only once the check passes it, or its entry
says *unsigned* or *none*. Which datasource supplies it is a convenience this decision
does not constrain.

**Hosts and deploys are unchanged.** `get_url`'s `checksum:` and `sha256sum -c` remain
the install-time control and a host pulls the pinned digest. No host gains `gpg`, `gh`
or `cosign`, or a call to a publisher or signer.

## Alternatives considered

- **Verify at deploy time.** A host would need the tools and a network path to a publisher
  or signer when it is provisioned, to repeat what a pull request can refuse before it is
  merged. The trust anchor is the same either way.
- **Trust the hash or digest Renovate derives.** The earlier position. It protects against
  a change after pinning and not against the source being wrong when it was pinned.
- **Sigstore bundles for OpenBao as well.** They need no committed key but bind the file to
  a workflow identity, which needs a verifier beyond `gh` and `gpg`. The GPG signature is
  used, and the bundle is a candidate if its key is rotated.
- **Accept BuildKit provenance as the statement.** Stored beside the image, so replaceable
  with it.
- **Require a signature for every artifact.** Most publishers offer none, so the check would
  fail on its first run and hold every pin; the tiers record what each publisher gives.
- **Vendor the artifacts, build from source, or rebuild every image in the repository's own
  registry.** A supply chain of the repository's own to keep current, or a build toolchain
  on the hosts, for a risk a reviewed pin already narrows.

## Consequences

- CI makes network calls to publishers, registries and GitHub's attestations API, and needs
  `gh` and `gpg` on the runner, a cosign container image, and a download of the uv tarball to
  verify its attestation.
- Committed keys are a trust anchor that needs review when it changes, and a publisher's key
  rotation, change of identity or end of signing fails the check until the entry is reviewed.
- Most entries are *unsigned*, *listed* or *none*, now recorded rather than implicit.
- A publisher's identity can be as wide as a branch, such as a reusable workflow at
  `refs/heads/main`; the entry records what the publisher offers and no more.
- The four image build workflows gain `id-token: write` and `attestations: write`.
- A digest-refresh pull request for a self-built image shows its attestation passing or
  failing, which a changed hash alone never did.
- A bump to a uv release without an attestation fails the check and holds that pull request.

## Invariants

- No key or identity is fetched when the check runs, and the one a signature or attestation
  must come from is committed in the repository.
- A *signed* artifact fails the check when its signature is missing, invalid or by another key;
  an *attested* one when its attestation is missing, invalid or for another repository; a
  *signed* image when its signature is missing or from another identity.
- A hash or digest is never accepted because Renovate produced it.
- No host needs `gpg`, `gh`, `cosign` or a publisher's or signer's network address to install a
  pinned release or run a pinned image.

## Non-goals

- OS packages installed by the package manager.
- Which registry an image comes from
  ([ADR 0108](../0108-which-images-a-deploy-runs-and-where-they-come-from/revision-000.md)).
- Verifying that a release or image is free of vulnerabilities
  ([ADR 0071](../0071-assessing-the-vulnerabilities-of-deployed-container-images/revision-000.md)).
- Reading an SBOM or a provenance document for what it says about the build.
- Signature checks on the repository's own commits, which the CD agent decision leaves
  unverified.

## Validation

- Unit tests generate a key and a clearsigned manifest: a matching hash passes; an altered
  line, a signature by a different key, a missing signature on a signed entry and a hash absent
  from the manifest each fail. Doubles for `gh` and `cosign` record their arguments, and a
  failing exit, a file that does not hash to the pin, an identity or repository other than the
  entry's and an entry with no identity each fail. A run against the wrong repository is a
  negative control that must fail, since `gh` prints nothing on success when not attached to a
  terminal and the check reads its exit code.
- A test asserts that every checksum pin and every image repository the tree pins has a
  registry entry.
- The weekly run.

## Reconsideration triggers

- A publisher begins to sign or attest, stops, changes between signatures and attestations,
  rotates its key or changes its identity, or a pin moves between tiers.
- Docker Hub or GHCR starts to verify a signature or attestation on pull.
- A publisher's statement becomes verifiable by a tool the runners already have, without
  `cosign`.
