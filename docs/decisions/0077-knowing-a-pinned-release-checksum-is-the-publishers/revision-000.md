---
id: ADR-0077
revision: 0
type: adr
title: Knowing a pinned release checksum is the publisher's
short: Pinned checksum verification
solution: A CI check verifies each pinned release hash against the publisher's signed manifest or the file's build attestation, with a key or identity fixed in the repository, and runs on every change to a pin and weekly
summary: How a sha256 pinned for a downloaded release binary is shown to be the hash its publisher signed, whoever or whatever copied it into the repository.
topic: security-hardening
status: accepted
related: [ADR-0044, ADR-0063, ADR-0064]
---

# 0077. Knowing a pinned release checksum is the publisher's

## Problem

Release binaries are installed on hosts and into an image under a pinned sha256, and the install stops if the file does not hash to it. The pin shows the file is the one that was pinned. It does not show the pinned hash is the one the publisher released, because each bump copies the new hash from the same place the file comes from. Whoever can replace a release asset on that host can replace the hash beside it, and a pull request carrying both looks the same to a reviewer as an honest one.

What has to be true: for every pinned release artifact, the hash in the repository is shown to be the one the publisher signed, where the publisher signs anything, and a pin the publisher gives no way to check is recorded as that rather than assumed.

## Context

Four pins are checksummed release downloads:

- `cd_agent_uv_sha256` and `cd_agent_rclone_sha256`, for the `uv` and `rclone` the CD agent host installs. That host holds the deploy job's credentials ([ADR 0044](../0044-prod-automation-trigger-and-execution/revision-000-c.md)), and `uv` and `rclone` run on it.
- `openbao_cli_deb_sha256`, for the OpenBao CLI `.deb` installed on `security`.
- `CODERABBIT_SHA256`, for the CLI zip unpacked in the review image ([ADR 0063](../0063-what-the-code-review-image-is-built-from-and-how-it-stays-current/revision-000.md)).

Each install verifies the file against the pin: `get_url` with `checksum:` in the roles, `sha256sum -c` in the Dockerfile. Renovate bumps the version in each, and the hash is bumped by a pull request note asking for a copy by hand, except `uv`, whose hash Renovate moves with its version from the release's `.sha256` asset. Whichever way the hash gets in, nothing compares it with anything the publisher signed.

`openbao_cli/defaults/main.yaml` states the current stance: the release's `checksums.txt` is signed as `checksums.txt.gpgsig`, "not independently verified here", because the repository's threat model already trusts GitHub-hosted release assets. That holds for an asset that is checked at a pinned hash. It is the weaker position for a hash that was copied from the asset's own release.

What the publishers offer, as far as is known:

- **rclone.** Its `SHA256SUMS` is clearsigned with the key whose fingerprint is `FBF737ECE9F8AB18604BD2AC93935E02FF3B54FA`, a 1024-bit DSA key ([release signing](https://rclone.org/release_signing)). Release 1.75.1's `SHA256SUMS` verified against that key under the default policy of GnuPG 2.4.8, which the `ubuntu-26.04` runner has, and of 2.4.4 on `ubuntu-latest`, and its `rclone-v1.75.1-linux-amd64.zip` line is the pinned hash. A GnuPG configured to reject weak digests may refuse older rclone signatures ([forum report](https://forum.rclone.org/t/sha-1-gpg-keys-are-deprecated-request-to-update-gpg-keys/49819)).
- **OpenBao.** `checksums.txt` is published with `checksums.txt.gpgsig` and `checksums.txt.sigstore.json`, and every asset has its own `.gpgsig` and `.sigstore.json`. The GPG signature is RSA by the subkey `E617DCD4065C2AFC0B2CF7A7BA8BC08C0F691F94`, which its install page ties to the primary key `66D15FDD87287219C8E15478D200CD702853E6D0` published at `openbao.org/assets/openbao-gpg-pub-20240618.asc`. Release 2.7.0's `checksums.txt.gpgsig` verified against that key on both runners, and the `deb`'s line in `checksums.txt` and the digest GitHub lists for it both equal the hash pinned at the time. `keys.openpgp.org` serves this key without its user ID, which GnuPG refuses to import, so a committed key comes from the publisher's own site.
- **uv.** A `.sha256` file beside each asset, and GitHub artifact attestations whose subject is the tarball's sha256, which for 0.12.23 is the pinned hash. `gh attestation verify uv-x86_64-unknown-linux-gnu.tar.gz --repo astral-sh/uv` exits 0 on that tarball on both runners. No detached signature is published. 0.12.23 was the newest release when this was checked, so a later release's attestation is not yet observed.
- **CodeRabbit.** `releases/<version>/SHA256SUMS`, with lines of the form `<hash>  ./coderabbit-linux-x64.zip`. No signature is published beside it: `SHA256SUMS.sig`, `.asc`, `.minisig`, `.gpg` and `.pem` all answer 404. The manifests are served to a GitHub-hosted runner, though `cli.coderabbit.ai`'s root answers 403.

From a GitHub-hosted runner, the manifest addresses, `api.github.com`, `github.com`, `downloads.rclone.org` and `openbao.org` answer, and a request with the job's token shows a 5000-an-hour limit; a run makes a handful of requests per artifact.

Renovate 44.138.0 applies a `digest` that a custom datasource returns for a release, and its `github-release-attachments` datasource maps a pinned hash to a new release's. Either supplies a hash; neither makes it the publisher's.

**Threat model.** The adversary can replace a release asset and the checksum file beside it, whether by taking the publisher's release account or a mirror, and cannot sign with the publisher's offline key. The assets are the credentials and authority of the host the artifact runs on. The attack path is a bump pull request whose new hash was derived from the tampered release; the install then verifies the file against a pin that was derived from the file.

## Decision

- **The check.** A stdlib-only Python check under `tools/ci`, unit-tested ([ADR 0064](../0064-where-the-code-behind-ci-and-documentation-checks-lives/revision-000.md)), reads a registry that holds one entry per pinned artifact: where its pin lives, the file name its manifest lists, the manifest's address for the pinned version, its tier, and for a signed artifact the signing key's fingerprint, and for an attested one the repository that must have built it.
- **Tiers.** A *signed* artifact's manifest and signature are fetched, the signature is verified with `gpg` in a throwaway keyring that holds only the key committed for that entry, and the pinned hash must equal the manifest's line for the file. An *attested* artifact is downloaded, must hash to the pinned value, and must pass `gh attestation verify` for the repository its entry names. A *listed* artifact has a manifest and no signature: the pinned hash must equal its line, which catches a hash copied from the wrong place and a typo, and no more. An artifact with *no* manifest says so in its entry. The registry is the one place a pin's tier is written down.
- **Keys.** The public key for a signed entry is committed in the repository with its fingerprint in the entry. The check accepts a signature only from that fingerprint and never fetches a key from a keyserver or a web page. A change of key is a reviewed diff.
- **When it runs.** On a pull request that changes a pinned file or the registry, and weekly, so a manifest or key that changes upstream is noticed without a pin changing. A failure on either fails the run.
- **Renovate proposes; the check decides.** A hash a datasource supplies is accepted into the pull request and trusted only once the check passes it. Which datasource supplies it is a convenience that this decision does not constrain.
- **Hosts and deploys.** Unchanged: `get_url`'s `checksum:` and `sha256sum -c` remain the install-time control, and no host gains `gpg` or a network call to a publisher.

## Alternatives considered

- **Verify the signature at deploy time.** A host would need `gpg`, the key and a network path to the publisher when it is provisioned, and the pinned hash it would then also check already decides the install. The trust anchor is the same key either way, and the check in CI can say no before the change is merged rather than when a host is provisioned.
- **Trust the hash Renovate derives.** It is the current position. It protects against a change after pinning and not against the source being wrong at the time.
- **Sigstore bundles for OpenBao too.** OpenBao publishes them beside its GPG signatures. They need no committed key, and bind the file to a GitHub workflow identity instead, which a verifier outside `gh` and `gpg` would have to be added for. The GPG signature is used, and the bundle is a candidate if its key is rotated.
- **Vendor the artifacts, or a mirror of them.** Large binaries and a supply chain of the repository's own to keep current.
- **Build from source.** The CD agent host and the review image would then need a build toolchain.

## Consequences

- CI makes network calls to publishers, as [`check-image-tags.yml`](../../topics/engineering/ci/gates.md#image-tag-existence-check) already does to registries.
- The committed keys are a trust anchor that needs review when it changes, and a publisher's key rotation fails the check until it is reviewed.
- The check needs `gh` and `gpg` on the runner, and downloads the uv tarball to verify its attestation.
- A bump to a uv release without an attestation fails the check, which holds that pull request until the maintainer decides.
- *Listed* and *none* artifacts stay trusted at the publisher's origin, now recorded in the registry rather than left implicit.
- A new pinned artifact needs a registry entry, which a test asserts for every checksum pin it can find.

## Invariants

- No key is fetched when the check runs.
- A signed artifact fails the check when its signature is missing, invalid or by another key, and an attested one when its attestation is missing, invalid or for another repository.
- A hash is never accepted because Renovate produced it.
- No host needs `gpg` or a publisher's network address to install a pinned release.

## Non-goals

- Container image signatures and digests.
- OS packages installed by the package manager.
- Verifying that a publisher's release is free of vulnerabilities ([ADR 0071](../0071-assessing-the-vulnerabilities-of-deployed-container-images/revision-000.md)).
- Signature checks on the repository's own commits, which ADR 0044 leaves unverified.

## Validation

- Unit tests generate a key and a clearsigned manifest: a matching hash passes; an altered line, a signature by a different key, a missing signature on a signed entry and a hash absent from the manifest each fail. For an attested entry, a double for `gh` records its arguments, and a failing exit, a file that does not hash to the pin and an entry with no repository each fail. `gh` prints nothing on success when not attached to a terminal, so the check reads its exit code, and a run against the wrong repository is a negative control that must fail.
- A test asserts that every checksum pin in the repository has a registry entry.
- The weekly run.

## Reconsideration triggers

- A publisher begins to sign, or stops signing, or changes between signatures and attestations.
- A publisher rotates its key.
- A pin moves between tiers.
