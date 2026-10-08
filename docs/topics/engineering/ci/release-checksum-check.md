# CI Release Checksum Check

Check that each pinned release hash is the publisher's. How it fits the pipeline is in [CI: PR Checks](pipeline.md); the scheduled-job overview is in [`scheduled-jobs.md`](scheduled-jobs.md).

Each downloaded release this repo pins by sha256 (uv, rclone, the OpenBao CLI
and the CodeRabbit CLI) is checked against the publisher: the pinned hash must
be the one the publisher signed, attested or lists, whoever copied it into the
file. The decision is
[ADR 0077 (Pinned checksum verification)](../../../decisions/0077-knowing-a-pinned-release-checksum-is-the-publishers/revision-000.md).
It runs in two places: the `release-checksums` job of `pr-checks.yml`, when a
PR changes the verifier and its keys or one of the files holding a pin, and
`check-release-checksums.yml`, once a week and on demand,
so a publisher's key rotation or moved manifest shows up even when no pin
changed. Both run `python3 -m ci.checksums.verify` from `tools/`, which is
standard-library only apart from the `gpg` and `gh` the runner image provides,
and which takes entry names to check just those. The job is not a matrix job,
so it can be required directly; a PR that changes no pin reports it skipped.

What is checked, per entry, is in
[`tools/ci/checksums/registry.py`](../../../../tools/ci/checksums/registry.py),
the registry of pins, with the files that hold each one and the address of its
publisher's manifest or artifact. A test fails when a pin in the repository has
no entry, so a new pin means a new entry.

## Tiers

An entry's tier says how far its pin can be checked, and the registry is
where each one is set:

| Tier | What the check does | Pins today |
| :--- | :--- | :--- |
| Signed | Fetches the publisher's manifest and its signature, verifies them with `gpg` in a throwaway keyring holding only the key committed under [`tools/ci/checksums/keys/`](../../../../tools/ci/checksums/keys/), and requires the pin to equal the manifest's line for the artifact. | rclone (clearsigned `SHA256SUMS`), the OpenBao CLI (`checksums.txt` and its detached `.gpgsig`) |
| Attested | Downloads the artifact, requires it to hash to the pin, then requires `gh attestation verify` to pass for the publisher's repository. | uv |
| Listed | Requires the pin to equal the publisher's manifest line. The manifest is unsigned, so this catches a hash copied wrongly, not a publisher that served a bad artifact. | the CodeRabbit CLI |
| None | The entry says why nothing can be checked. | none |

No key is fetched when the check runs: `gpg` runs with its network helper off,
the keyring is built from the committed file, and a key file must hold exactly
the fingerprint its entry names. A signature by an expired or revoked key, or
by any other key, fails. A publisher that rotates its key fails the weekly run
until the new key is reviewed and committed.

## When a pin, a key or a manifest changes

- **A new pin** needs a registry entry in the same change; a test fails for any
  checksum pin the registry doesn't name. The entry sets its tier, and a signed
  one also names the fingerprint and a key file under `tools/ci/checksums/keys/`.
- **A bump** (Renovate or by hand) is checked by the `release-checksums` job.
  A hash that differs from what the publisher signed, attested or lists fails
  it, whatever produced the hash. A uv release without an attestation fails its
  bump PR until the maintainer decides what to do about it.
- **A publisher's key rotates:** the weekly run fails until the new key is
  reviewed and committed, with the entry's fingerprint changed to match. The
  key file must hold that one key and nothing else, which a test checks.
- **A manifest moves:** the entry's address is stale and the run fails on it.
  The check depends on each publisher keeping its manifest where it is.
- **A publisher starts to sign**, or stops: the entry's tier changes in the
  registry. The CodeRabbit CLI's release bucket publishes no signature file
  beside its manifest or its archives, so its pin stays *listed*.

Failures are per entry and the run reports every entry before it exits
non-zero, with each failure as an `::error::` annotation. A publisher that
can't be reached after three attempts (429, 5xx or a network error are
retried) fails its entry: unlike the image tag check, a pin that couldn't be
checked is not a pass. The weekly run's token is the workflow's own read-only
`GITHUB_TOKEN`, used only by `gh attestation verify`.

The tests speak to a local server and generate their own keys and signatures;
they don't reach a publisher. The first run of each workflow is the live
check, and a pinned hash changed to a wrong one is the way to see the PR run
fail.
