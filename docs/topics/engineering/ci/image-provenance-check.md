# CI Image Provenance Check

Check that each pinned image digest is one its publisher signed or attested.
The scheduled-job overview is in [`scheduled-jobs.md`](scheduled-jobs.md).

Every image this repo deploys is pinned as `name:tag@sha256:digest`, which
shows an image is the one that was pinned and not that the digest is the one the
publisher built: Renovate records whatever the registry served. The check
verifies each pinned digest against a statement its publisher made, with the
signer fixed in this repository, so a pull request that moves a pin to someone
else's image fails whatever opened it. The decision is
[ADR 0084 (Image digest provenance)](../../../decisions/0084-knowing-a-pinned-image-digest-is-the-publishers/revision-000.md).
No workflow runs it yet; it is run by hand from `tools/`:

```bash
cd tools && python3 -m ci.provenance.verify [IMAGE ...]
```

It is standard-library only apart from the tools it calls: `gh` with `GH_TOKEN`
set for attested entries, and `cosign` for signed ones. Naming an image, as its
registry entry writes it, checks just that one. Hosts are unchanged: a host
pulls the pinned digest, and none has `gh`, `cosign` or a path to a signer.

What is checked, per image repository, is in
[`tools/ci/provenance/registry.py`](../../../../tools/ci/provenance/registry.py):
one entry per repository, holding its tier and whatever that tier trusts.
The repository, the certificate identity and the key come from the entry in the
tree, never from the registry or the image being checked, so changing one is a
reviewed diff. Two entries for one repository are refused, since a digest could
then pass on either one's terms. The registry holds no entries yet, so a run
reports no images.

## Tiers

| Tier | What the check does |
| :--- | :--- |
| Attested | Runs `gh attestation verify` on each pinned digest for the GitHub repository the entry names. |
| Signed | Runs `cosign verify` on each pinned digest, with the certificate identity and OIDC issuer the entry fixes, or with the public key committed for it under `tools/ci/provenance/keys/`. |
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
