---
id: ADR-0084
revision: 0
type: adr
title: Knowing a pinned image digest is the publisher's
short: Image digest provenance
solution: A CI check verifies each pinned image digest against the publisher's cosign signature or GitHub attestation, with the signer's identity fixed in the repository, records an image with no verifiable statement as unsigned, and the repository's own images are attested by their build workflows
summary: How a digest pinned for a container image is shown to be the one its publisher built, whoever or whatever copied it into the repository.
topic: security-hardening
status: working
related: [ADR-0063, ADR-0077, ADR-0083]
---

# 0084. Knowing a pinned image digest is the publisher's

## Problem

Every image the repository deploys is pinned as `name:tag@sha256:digest` ([ADR 0083 (Images a deploy runs)](../0083-making-a-deploy-run-the-images-its-commit-names/revision-000.md)), and a host pulls exactly that digest. The pin shows the image is the one that was pinned. It does not show the pinned digest is the one the publisher built, because Renovate records whatever the registry served when it ran. Whoever can push to a publisher's registry namespace controls both the image and any statement stored beside it, and a pull request moving a digest to their image looks the same to a reviewer as an honest one.

What has to be true: for every pinned image, the digest is shown to be one its publisher signed or attested, where the publisher offers a statement that can be checked, and an image whose publisher offers none is recorded as that rather than assumed.

## Context

- **What a registry can hold beside an image.** BuildKit attaches SBOM and provenance attestations to the image index as in-toto JSON in a manifest of the same image ([Docker build attestations](https://docs.docker.com/build/metadata/attestations/)). `docker/build-push-action` 4 or later adds provenance by default, at `mode=max` for a public repository and `mode=min` for a private one, and adds an SBOM only when asked ([Docker: attestations in GitHub Actions](https://docs.docker.com/build/ci/github-actions/attestations/)). The pages read for this record do not say that a BuildKit attestation is signed, and nothing in them fixes who may produce one.
- **GitHub artifact attestations.** `actions/attest` signs an attestation with a short-lived Sigstore certificate, from the public-good Sigstore instance for a public repository, and stores it in GitHub's attestations API, tied to the repository whose workflow ran ([actions/attest](https://github.com/actions/attest)). For a container image the workflow needs `id-token: write`, `attestations: write` and `packages: write`, names the image without a tag as `subject-name`, and passes the pushed digest as `subject-digest`; `push-to-registry` also stores the attestation in the registry ([GitHub: use artifact attestations](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations)). A consumer verifies with `gh attestation verify oci://<image> -R <owner>/<repo>`, which that page shows after a `docker login`. `gh`'s manual says an `oci://` reference needs the caller already authenticated with its registry, fixes who may have signed with `--repo`, `--owner`, `--signer-workflow` or `--cert-identity`, and reads a Sigstore trust root from disk with `--custom-trusted-root` ([gh attestation verify](https://cli.github.com/manual/gh_attestation_verify)). Public repositories can use them on every current plan. `actions/attest-build-provenance` 4 is a wrapper around `actions/attest`, and its README directs new uses to `actions/attest`.
- **What cosign offers.** `cosign verify` fixes a keyless identity with `--certificate-identity` or `--certificate-identity-regexp` and its issuer with `--certificate-oidc-issuer` or `--certificate-oidc-issuer-regexp`, and requires one of each, and it reads a Sigstore trust root from disk with `--trusted-root` ([cosign verify](https://github.com/sigstore/cosign/blob/main/doc/cosign_verify.md)). cosign is published as the container image `ghcr.io/sigstore/cosign/cosign` ([README](https://github.com/sigstore/cosign#readme)). The `ubuntu-26.04` runner image lists GitHub CLI, Skopeo and Docker, and does not list cosign ([runner image](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2604-Readme.md)).
- **What [ADR 0077 (Pinned checksum verification)](../0077-knowing-a-pinned-release-checksum-is-the-publishers/revision-000.md) already does.** It verifies a release artifact with `gh attestation verify` against a repository the registry entry fixes, with no key or identity fetched when the check runs, and puts container image signatures and digests out of its scope. This record covers that scope and reuses the design.
- **What publishers offer, as far as is known.** This is read from each publisher's workflow files on its default branch, not from its registry, which this environment cannot reach: a workflow that signs says what the publisher intends, and the registry holds what it did.

  | Image | Publisher's workflow shows |
  | :--- | :--- |
  | `ghcr.io/11notes/kms` | A GitHub attestation of build provenance for the pushed digest, named after the Docker Hub image and kept in GitHub's API (`push-to-registry: false`), plus a BuildKit SBOM and `mode=max` provenance. Its `kms-gui` image was not examined. |
  | `ghcr.io/lissy93/dashy` | GitHub attestations for the SBOM and for build provenance, pushed to GHCR. Two of its build steps set `provenance: false`. |
  | `openbao/openbao` | One build pushed to `docker.io`, `ghcr.io` and `quay.io`, and `cosign sign --yes` on every tag at that one digest. Its build sets `org.opencontainers.image.source`. |
  | `smallstep/step-ca`, `smallstep/step-cli` | A shared workflow that names no registry but Docker Hub and runs `cosign sign --yes` on the image at its digest. |
  | `curlimages/curl` | A release workflow that pushes the image to Docker Hub and to `ghcr.io/curl/curl-container`, and runs `cosign sign` with a private key on each. The public half, `cosign.pub`, is in the publisher's repository. |
  | `rclone/rclone`, `ghcr.io/itzg/minecraft-server` | `provenance: false` on the image build, and no attestation or signing step. |
  | `ghcr.io/chrislusf/seaweedfs` | `provenance: false` on one build, and a comment that a cosign signature is attached to the digest, with no signing step in the file it is in. |
  | The rest of the images the repository pins | No signing step and no GitHub attestation step found, or the build is in a shared workflow that was not followed. `ghcr.io/henrygd/beszel` requests a BuildKit SBOM and `mode=max` provenance, with no signing step beside them. |

- **The repository's own images.** `ghcr.io/wenenhoe/*` are built by `build-*-image.yml` with `docker/build-push-action` from a public repository, so they should carry default BuildKit provenance, which was not observed in the registry. None of the four workflows requests an attestation, asks for `id-token: write`, or signs, so nothing ties one of those digests to the workflow that built it.
- **Who may push.** A namespace such as `ghcr.io/wenenhoe` is written by the repository's own workflow token and by whoever holds the account, which makes a self-built image's digest the same kind of unproven copy as any other.

**Threat model.** The adversary can push to a publisher's registry namespace, or to the repository's own, and cannot make a Sigstore signing identity or a signing key it does not hold sign for it. The assets are the hosts that run the image and what the container can reach. The attack path is a digest-refresh pull request, opened by Renovate from whatever the registry served, that moves a pin to the adversary's image, which a reviewer sees only as a changed hash.

## Decision

- **The check.** A stdlib-only Python check under `tools/ci`, unit-tested ([ADR 0064 (CI and doc check code)](../0064-where-the-code-behind-ci-and-documentation-checks-lives/revision-000.md)), reads a registry that holds one entry per image repository: its tier and, for the tier, the identity that must have signed it. It takes every pinned digest of that repository from the tree and verifies each.
- **Tiers.** An *attested* image must pass `gh attestation verify` for the repository its entry names. A *signed* image must pass `cosign verify` with the certificate identity and OIDC issuer its entry fixes, or, for a publisher that signs with a key, the public key committed for it. An *unsigned* image has no statement the check can verify, and its entry says so. A BuildKit attestation or an SBOM that nothing ties to an identity the repository fixes does not lift an image out of *unsigned*. The registry is the one place an image's tier is written down.
- **No key or identity is fetched.** The repository named, the certificate identity and the key come from the entry, never from the registry or the image being checked. A change of one is a reviewed diff. The Sigstore trust root a verifier uses is not an entry's identity and is not covered by this.
- **Self-built images are attested.** Each `build-*-image.yml` attests the digest it pushes with `actions/attest`, with the permissions that action needs and no more, and each `ghcr.io/wenenhoe/*` image is an *attested* entry naming this repository.
- **Tools.** `gh` comes from the runner image and `cosign` runs as its container image, pinned by digest like any other image ([ADR 0083 (Images a deploy runs)](../0083-making-a-deploy-run-the-images-its-commit-names/revision-000.md)), so no workflow installs a binary.
- **When it runs.** On a pull request that changes a pinned image reference or the registry, and weekly, so a signature or an attestation that disappears is noticed without a pin changing. A failure on either fails the run.
- **Renovate proposes; the check decides.** A digest Renovate records is accepted into the pull request and trusted only once the check passes it, or its entry says *unsigned*.
- **Hosts and deploys.** Unchanged: a host pulls the pinned digest, and no host gains `gh`, `cosign` or a call to a signer.
- **A new image needs an entry.** An image the repository pins with no registry entry fails a test, as a checksum pin does in ADR 0077.

## Alternatives considered

- **Verify at deploy time.** A host would need `gh` or `cosign` and a network path to a signer when it is provisioned, to repeat what a pull request can refuse before it is merged. The trust anchor is the same either way.
- **Trust the digest Renovate records.** The current position. It protects against a change after pinning and not against the source being wrong when it was pinned.
- **Accept BuildKit provenance as the statement.** It is stored beside the image, so a party able to replace the image in a namespace can replace it too, unless something signs it with an identity the repository fixes.
- **Require a signature for every image.** Most publishers offer none, so the check would fail on its first run and hold every pin until it was waived one by one. The tiers record what each publisher gives.
- **Rebuild every image in the repository's own registry.** A build and a registry to keep current for each image, to answer a risk that a pinned digest already narrows to a reviewed pull request.

## Assumptions

- **Claim:** `gh attestation verify oci://<name>@sha256:<digest> -R <owner>/<repo>` verifies a digest-pinned reference of a public GHCR image from a GitHub-hosted runner logged in to `ghcr.io` with the job's own token, which is the authentication its manual requires.
  **Breaks if wrong:** The *attested* tier needs a credential the job does not have, or a downloaded subject, as ADR 0077 does for a release tarball.
  **Checked by:** The provenance spike's `self-attest` run on an image built and attested by its own workflow, and its `attested` probe against `ghcr.io/lissy93/dashy` and `ghcr.io/11notes/kms`.
- **Claim:** The registry holds what each publisher's workflow says it does: a signature for the digest the repository pins, from the identity the workflow runs as.
  **Breaks if wrong:** An entry's tier is wrong, and the check fails on its first run or accepts nothing.
  **Checked by:** The spike's `probe-registries` run against each pinned digest of the images in the table above.
- **Claim:** A keyless certificate identity of a publisher can be written as one fixed value or one anchored pattern that holds across its releases.
  **Breaks if wrong:** Every release fails the check, or the pattern is wide enough to accept a signature from a workflow the publisher did not mean.
  **Checked by:** The spike's `identity_history` section, which reads the certificate identity on the newest releases of each keyless-signed image.
- **Claim:** cosign, run as its container image on a runner, verifies the signatures that publishers made with cosign 2.x.
  **Breaks if wrong:** The check pins an older cosign image, or those signatures need another verifier.
  **Checked by:** The spike's `keyless` and `keyed` sections, run with `v2.6.2` and `v3.1.3`.

## Consequences

- Most entries start as *unsigned*, because most publishers offer nothing to verify. The registry says that, where today it is implicit.
- A publisher that stops signing, or changes its signing identity, fails the check until the entry is reviewed.
- CI makes network calls to registries and to GitHub's attestations API, as [`check-image-tags.yml`](../../topics/engineering/ci/image-tag-check.md) already does to registries, and runs a cosign container image beside the `gh` the runner already has.
- The four build workflows gain `id-token: write` and `attestations: write`, permissions a workflow that holds a package-write token has not had.
- A digest-refresh pull request for a self-built image shows its attestation passing or failing, which a changed hash alone never did.

## Invariants

- The identity a signature or attestation must come from is committed in the repository.
- A *signed* or *attested* image fails the check when its statement is missing, invalid, or from another identity or repository.
- A digest is never accepted because Renovate produced it.
- No host needs `gh`, `cosign` or a signer's network address to run a pinned image.

## Non-goals

- Which registry an image comes from (a separate decision).
- Release binaries and their checksums, which ADR 0077 covers.
- Verifying that an image is free of vulnerabilities ([ADR 0071 (Image vulnerability assessment)](../0071-assessing-the-vulnerabilities-of-deployed-container-images/revision-000.md)).
- Reading an SBOM or a provenance document for what it says about the build.
- Signature checks on the repository's own commits.

## Validation

- Unit tests double `gh` and `cosign`, as ADR 0077's do for `gh`: a failing exit, an identity other than the entry's, a repository other than the entry's and an entry with no identity each fail, and a run against the wrong repository is a negative control that must fail.
- A test asserts that every image repository the tree pins has a registry entry.
- The weekly run.

## Reconsideration triggers

- A publisher begins to sign or attest, stops, or changes its identity.
- Docker Hub or GHCR starts to verify a signature or attestation on pull.
- A publisher's statement becomes verifiable by a tool the runners already have, without `cosign`.
