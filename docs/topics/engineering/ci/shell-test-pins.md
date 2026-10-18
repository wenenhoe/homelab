# CI Shell Test Pins

The Bats runner and its two helper libraries the shell tests run on, pinned by commit, and the check that each pin is what its release tag names. How it fits the pipeline is in [CI: PR Checks](pipeline.md). The decision is [ADR 0086 (Shell script tests)](../../../decisions/0086-testing-the-control-flow-of-shell-scripts/revision-000.md).

[`tools/ci/shell_tests/pins.txt`](../../../../tools/ci/shell_tests/pins.txt) holds one entry per line: a GitHub repository, a release tag and the full commit SHA the tag points at. `bats-core`, `bats-support` and `bats-assert` are the entries. A line that isn't `repository tag sha` fails every command below, as does a tag or repository shaped like anything but a release tag or an `owner/name`, since both go to `git` as arguments and the file is changed by pull requests. Two repositories with one name fail too: the name is the directory a fetch clones into.

Both commands are standard library only, run from `tools/` on the runner's own `python3`, and need `git`.

## Fetching the clones

`python3 -m ci.shell_tests.fetch DIR` clones each pin into `DIR/<repository name>` by its SHA, not its tag, and refuses unless the clone's `HEAD` equals the SHA.

- A directory that is already there is never modified. It is accepted when its `HEAD` is the pin and refused otherwise, with a message to remove it, so a clone left at an older pin is not run in place of the new one. A directory that holds no clone is refused the same way, even when it sits inside another repository.
- A fetch that fails leaves no directory behind, so a retry starts clean.
- `GIT_TERMINAL_PROMPT=0` is set, so a repository that is not there fails instead of asking for a username.

## Checking the pins

`python3 -m ci.shell_tests.pins check` resolves each entry's tag with `git ls-remote` and fails when it does not point at the pinned SHA. An annotated tag is a tag object, so the check reads the commit it peels to; a lightweight tag is the commit itself. A pin copied from the tag object instead of the commit fails.

It reports every entry before it exits non-zero, each failure as an `::error::` annotation. A tag that is missing or moved is a clean answer; a repository that can't be reached is retried three times and then fails: a pin that could not be checked has not been shown to be the publisher's.

## What the check proves

Every entry is at the *listed* tier of [ADR 0077 (Pinned checksum verification)](../../../decisions/0077-knowing-a-pinned-release-checksum-is-the-publishers/revision-000.md). The check catches a SHA copied wrongly and a tag that was moved. It does not show the commit to be the maintainers': every published copy of the key that signed the `bats-core` and `bats-assert` tags has expired, and `bats-support`'s tag is not signed. A commit the publisher did not intend, behind a tag moved with it, would pass.

## Where it runs

The `shell-tests` job of `pr-checks.yml` fetches the clones on every pull request it runs for ([CI Shell Tests](shell-tests.md#in-ci)), and checks the pins when the pin file or the tooling beside it changed.

`check-shell-test-pins.yml` runs the same check once a week and on demand, so a tag the publisher moves or deletes is noticed when no pin changed ([scheduled jobs](scheduled-jobs.md#shell-test-pin-check)). It needs no token: the repositories are public and the workflow reads nothing else.

## Bumps

A regex manager in [`renovate.json5`](../../../../.github/renovate.json5) reads every entry line of the pin file, tag and SHA together, and writes a bump back as one line. Where the `github-tags` datasource can't supply a new tag's SHA, nothing proposes a bump and one is made by hand: change the tag and the SHA on the line, and run the check. Either way the check decides.

The tests run `git` against real local repositories and never reach GitHub; the two commands above are the live check.
