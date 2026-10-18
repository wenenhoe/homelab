# CI Image Provenance Check

Check that each pinned image digest is one its publisher signed or attested.
How it fits the pipeline is in [CI: PR Checks](pipeline.md); the scheduled-job
overview is in [`scheduled-jobs.md`](scheduled-jobs.md).

Every image this repo deploys is pinned as `name:tag@sha256:digest`, which
shows an image is the one that was pinned and not that the digest is the one the
publisher built: Renovate records whatever the registry served. The check
verifies each pinned digest against a statement its publisher made, with the
signer fixed in this repository, so a pull request that moves a pin to someone
else's image fails whatever opened it. The decision is
[ADR 0084 (Image digest provenance)](../../../decisions/0084-knowing-a-pinned-image-digest-is-the-publishers/revision-000.md).
It runs in two places: the `provenance` job of `pr-checks.yml`, when a PR changes
the checker, its registry or keys, or a file that can hold a pinned image
reference, and `check-image-provenance.yml`, once a week and on demand, so a
signature or attestation that disappeared, or an identity that changed, shows up
even when no pin did. Both run `python3 -m ci.provenance.verify` from `tools/`,
and it can be run by hand the same way:

```bash
cd tools && python3 -m ci.provenance.verify [IMAGE ...]
```

It is standard-library only apart from the tools it calls: `gh`, which the runner
image provides and which `GH_TOKEN` authenticates for attested entries, and
`docker`, which runs `cosign` for signed ones. Naming an image, as its registry
entry writes it, checks just that one. The job is not a matrix job, so it can be
required directly; a PR that changes no image reference reports it skipped. The
weekly run's token is the workflow's own read-only `GITHUB_TOKEN`, and no workflow
installs a binary. Hosts are unchanged: a host pulls the pinned digest, and none
has `gh`, `cosign` or a path to a signer.

`cosign` runs as the image named by `COSIGN_IMAGE` in
[`verify.py`](../../../../tools/ci/provenance/verify.py), pinned by digest, tracked
by a Renovate manager and checked like any other pinned image by
[`image-tag-check.md`](image-tag-check.md). It stays at version 3 or later: version
2 finds no signature on some images that version 3 verifies. The container drops
every capability, caches its trust root under `/tmp` because the image runs as
non-root and distroless, and sees nothing of the tree except a signed entry's one
key file, mounted read-only.

What is checked, per image repository, is in
[`tools/ci/provenance/registry.py`](../../../../tools/ci/provenance/registry.py):
one entry per repository, holding its tier and whatever that tier trusts.
The repository, the certificate identity and the key come from the entry in the
tree, never from the registry or the image being checked, so changing one is a
reviewed diff. Two entries for one repository are refused, since a digest could
then pass on either one's terms. A test fails when a repository the tree names has
no entry, or an entry names one the tree does not, so a new image means a new
entry.

## Tiers

| Tier | What the check does |
| :--- | :--- |
| Attested | Runs `gh attestation verify` on each pinned digest for the GitHub repository the entry names. |
| Signed | Runs `cosign verify` in the container on each pinned digest, with the certificate identity and OIDC issuer the entry fixes, or with the public key committed for it under [`tools/ci/provenance/keys/`](../../../../tools/ci/provenance/keys/). |
| Unsigned | Runs nothing and passes. The entry says why the publisher gives nothing to verify. |

A BuildKit attestation or an SBOM that nothing ties to an identity the
repository fixes does not lift an image out of *unsigned*: whoever can replace
an image in a namespace can replace what is stored beside it.

A signed entry's identity is written out, or is a pattern anchored from
`^https://` and a literal host to `$`. Both `cosign verify` and the library
under it match an unanchored pattern anywhere in the certificate's identity, so
an unanchored entry would accept any identity that merely contains it. An entry
with neither an identity nor a key, or with both, cannot be built, and `cosign
verify` itself refuses an identity without an issuer in keyless mode.

## When an image or its publisher changes

- **A new image** needs a registry entry in the same change, *unsigned* when its
  publisher offers nothing to verify, with the reason written in the entry.
- **A bump** is checked by whichever tier the entry sets. A digest the publisher
  did not sign or attest fails, whatever produced it.
- **A publisher starts to sign**, or stops, or changes its signing identity: the
  entry's tier or identity changes in its own reviewed change, and the check
  fails until it does.
- **A Renovate bump of the cosign image** is an ordinary digest refresh: the job
  runs on it, since the file holding the pin is in the filter, and the image is a
  registry entry like any other.
- **A key-signing publisher rotates its key:** the new public key replaces the
  file under `tools/ci/provenance/keys/`, which holds exactly one key.

## The repository's own images

Each `build-*-image.yml` attests the digest it pushes with `actions/attest`,
pinned to a commit, naming the image without a tag and passing the digest
`docker/build-push-action` reports. The attestation is also pushed to the
registry beside the image. Only the build job holds `id-token: write` and
`attestations: write`, on top of the `contents: read` and `packages: write` it
already had; the storage record the action can create is turned off, since it
would need a further permission nothing here uses.

The compose pins for `caddy-digitalocean` and `wastebin` name attested digests,
so their entries are *attested* for `wenenhoe/homelab`. Molecule's platform
image is referenced by its floating `:latest` tag, so no digest is pinned for
the check to verify and its entry stays *unsigned*. A pin that moves to a
digest built before the workflow attested fails the check.
Verify a build by hand with `gh attestation verify
oci://ghcr.io/wenenhoe/<name>@<digest> --repo wenenhoe/homelab`.
[`test_provenance_build_workflows.py`](../../../../tools/tests/ci/provenance/test_provenance_build_workflows.py)
holds the permissions, the action's pin and the subject each workflow names.

## Which digests

Every digest the tree pins for an entry's repository is verified, found the way
[`image-tag-check.md`](image-tag-check.md) finds every pinned reference:
compose files, Dockerfiles, Ansible and the Renovate-tracked variables. A
reference with no digest has nothing to verify and is left out. The tools are
given `host/repository@digest`, never the tag, and Docker Hub images by
`docker.io`, the name its images go by.

A digest and a repository name become part of one argument to `gh` or
`cosign`, and both come from files a pull request changes. A reference that is
not a lower-case repository at a `sha256` digest fails the run before any tool
sees it. A Renovate manager that no longer matches a file also fails the run,
since a pin the collector cannot see is a pin nothing verified. An entry whose
repository has no pinned digest is reported as a notice and passes.

## A call that gets no answer

Neither tool's exit status separates a missing statement from a registry or
API that did not answer, so a digest that could not be verified fails its
entry, as in [`release-checksum-check.md`](release-checksum-check.md) and
unlike the image tag check, where a silent registry is a warning. Each call is
made up to `ATTEMPTS` times (see
[`verify.py`](../../../../tools/ci/provenance/verify.py)), pausing longer
between attempts, so a failure that passes on a second try does not fail a run
and a statement that is missing fails every attempt. A tool that is not
installed fails at once. A publisher that moves or rotates its signing identity
fails the entry until a human reviews it.

Failures are per digest and the run reports every entry before it exits
non-zero, each as an `::error::` annotation naming the digest and the files that
pin it, and writes the same lines to the job summary under `GITHUB_STEP_SUMMARY`
when it runs in Actions.

## Tests

The tests double `gh` and `cosign` with stand-ins that exit 0 only for the
repository, identity or issuer the real tool would accept, so an entry that
names another one must fail. They cover a failing exit, a retry that passes, a
missing tool, an identity, an issuer or a repository other than the entry's,
and a key that is not committed. They do not reach a registry or GitHub.
