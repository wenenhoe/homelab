---
id: ADR-0086
revision: 0
type: adr
title: Testing the control flow of shell scripts
short: Shell script tests
solution: "Bats tests under tools/tests/shell, run by a CI job on bats-core, bats-support and bats-assert cloned at commits pinned in one file, with every external tool stubbed on PATH"
summary: How the branching and failure handling of the repo's shell scripts is unit-tested, given that only a linter reads them today and Molecule exercises only some of them against real services.
topic: repository-tooling
status: working
related: [ADR-0064, ADR-0069, ADR-0070, ADR-0077, ADR-0083, ADR-0084, ADR-0085]
---

# 0086. Testing the control flow of shell scripts

## Problem

Some of the repo's shell scripts decide something that matters: whether a stack is left stopped after a failed restore, whether a token is revoked and a scratch directory removed on every exit path, whether a stale backup suppresses a push without failing the unit. Nothing asserts those decisions. A change that breaks one passes every check that runs today.

What has to be true: the branches of such a script can be exercised without the services it drives, a failing case names the behavior that broke, the tool that runs the tests is installed from a source the repo can pin and verify, and it runs where the repo's other tests run.

## Context

The repo tracks 18 `.sh` or `.sh.j2` files. `shellcheck` reads all of them as text. Molecule runs the three templated ones (`check-freshness`, the Caddy certificate check and `cloud-sync`'s `run.sh`) against real targets. No scenario, test or workflow runs `run_restore.sh`, `run_upgrade.sh` or `snapshot-push.sh`, and `molecule-test-all.sh` is run only by the CI job that calls it and by hand. Python code is covered by pytest under `tools/tests/` and `ansible/tests/` ([ADR 0069 (Python test style)](../0069-how-python-unit-tests-are-written-and-run/revision-000.md)); nothing there reaches a script's own control flow.

Most of a script's branches turn on the exit status of one external command (`docker`, `bao`, `rclone`, `ssh`, `openssl`) and on what the script then does. A test of such a branch needs the command to succeed or fail on demand and a record of what the script ran afterwards.

Bats ([bats-core](https://github.com/bats-core/bats-core)) is a test runner written in Bash. A test is a function; `run` captures a command's status and output; each test gets its own temporary directory. `bats-assert` and `bats-support` supply the assertions. `bats-core` needs Bash 3.2 or newer, and runs tests serially unless GNU parallel is installed.

How the pieces are published, as read when this was written:

- `bats-core` publishes signed, annotated release tags, v1.14.0 the latest. `bats-assert` signs its v2.2.4 tag with the same key ID the `bats-core` tags name. `bats-support` has no release newer than v0.3.0, whose tag is not signed, and its default branch is 37 commits ahead of that tag. `bats-assert` loads `bats-support`.
- npm carries `bats` at 1.13.0 while v1.14.0 is the latest release. Distribution packages follow the distribution; Ubuntu 25.04 carries 1.11.1.
- The `bats/bats` image is built on `docker.io/bash`, an Alpine image. Its release workflow signs and attests nothing and pushes tags under the Docker Hub account only. The image holds `bats`, the helper libraries and GNU parallel; it has no Python, `uv` or Docker CLI.
- A GitHub checkout of a commit needs only Git and GitHub. An image needs a Docker daemon and a registry.

The hosts run Ubuntu and the CI jobs run on `ubuntu-26.04`, both with GNU coreutils. An Alpine image has busybox applets in their place.

A script that is a Jinja2 template has to be rendered before it runs. Jinja2 is already in `uv.lock` through Ansible.

[ADR 0077 (Pinned checksum verification)](../0077-knowing-a-pinned-release-checksum-is-the-publishers/revision-000.md) and [ADR 0084 (Image digest provenance)](../0084-knowing-a-pinned-image-digest-is-the-publishers/revision-000.md) require a pin to be shown to be the publisher's, with the signer's identity fixed in the repo; [ADR 0083 (Images a deploy runs)](../0083-making-a-deploy-run-the-images-its-commit-names/revision-000.md) pins every image by digest; [ADR 0085 (Image registry choice)](../0085-choosing-the-registry-an-image-is-pulled-from/revision-000.md) pulls a new image from the registry its publisher signs on.

## Decision

Shell tests are Bats files under `tools/tests/shell/`, one per script, beside the Python tests.

- **Which scripts.** A script gets a test file when it has a branch that decides an outcome worth protecting: a failure path, a cleanup guarantee, a confirmation, an exit status others rely on. A script that only assembles one `docker run` or `docker exec` invocation does not. The first set is `run_restore.sh`, `snapshot-push.sh`, `molecule-test-all.sh`, `run_upgrade.sh` and the two templated checks; the others are decided script by script.
- **Install.** The runner and its two libraries are cloned from GitHub at full commit SHAs recorded in one committed file, each fetched by SHA and refused unless `HEAD` equals the pin. The pin file names a release tag beside each SHA. No image, npm package or distribution package is used, and no git submodule is added.
- **Provenance.** `bats-core` and `bats-assert` are pinned to a commit their signed release tag points at, and a check verifies that tag against a public key committed in the repo with its fingerprint fixed in the pin entry, in the way [ADR 0077](../0077-knowing-a-pinned-release-checksum-is-the-publishers/revision-000.md) treats a signed manifest. `bats-support` has no signed tag; its entry says it is unsigned and is pinned by SHA only.
- **Bumps.** Renovate proposes a new tag and SHA in a pull request; the check decides, as in ADR 0077 and ADR 0084.
- **Isolation.** The harness puts a directory of stubs first on `PATH`, and installs a stub that fails loudly for every external tool a script under test calls, before any test runs. A test replaces the stubs it needs. A test that forgets one therefore fails instead of running the real `docker`, `ssh` or `bao`. A stub appends its argv to a log and exits as the test directs. A test writes only under its own temporary directory.
- **Templates.** A `.sh.j2` script is rendered by Jinja2 with strict undefined variables and the test's own variables, and the result is run. Molecule stays the authority on how Ansible renders it.
- **Assertions.** A test ends in an assertion on an outcome the script decides: an exit status, an output line, a file or directory that exists or does not, or the order of calls in the stub log. A negated check is `run !`, never a bare `!`.
- **CI.** A `shell-tests` job in `pr-checks.yml`, scoped by `detect-changes` to changes in a shell script, a shell test or the pin file, runs the suite on the runner's own Bash and GNU userland. `check-doc-drift` ties the job to its docs as it does the others.
- **Lint.** The existing `shellcheck` hook already treats `.bats` files as shell. No new hook is added.
- **Docs.** A "Shell tests" section in [`conventions.md`](../../topics/engineering/conventions.md) states the style, and the pipeline docs describe the job, in the changes that add them.

## Alternatives considered

- **The `bats/bats` image.** It needs no clone, and its libraries are included. It loses on four counts: its userland is busybox, not the GNU tools the scripts run on, so a test of `date -d` or `stat -c` there would not describe the host; it holds no Python or `uv`, so templated scripts could not be rendered in it without a derived image the repo would build, attest and register; ADR 0084 would record it *unsigned*, because its release workflow signs and attests nothing; and ADR 0085 prefers the registry a publisher signs on, and its workflow pushes to Docker Hub only.
- **npm (`npm install bats`).** It adds Node and a lockfile to a repo that has neither for any other purpose, and it lags the GitHub release.
- **A distribution package.** It follows the distribution's schedule and cannot be pinned by the repo.
- **A git submodule.** It pins the commit natively, but it puts a third-party tree into every checkout the repo has, including the CD agent's fetch, for a tool only CI and the maintainer use.
- **Vendoring the three trees.** It makes the code reviewable in the diff, copies about 4 MB of third-party code into the repo, and leaves Renovate nothing to bump.
- **Pytest driving the scripts through `subprocess`.** It needs no new runner and follows [ADR 0069](../0069-how-python-unit-tests-are-written-and-run/revision-000.md) and [ADR 0070 (Test doubles binding)](../0070-what-a-unit-tests-doubles-are-bound-to/revision-000.md) unchanged. Each test would write executable stubs and drive `read` prompts from Python, in a second language from the script it tests. This was not prototyped; it is the option to fall back to if the pinned clone proves a burden.
- **Molecule alone.** It runs the real services, so it stays. It cannot cheaply reach a failure branch such as a restore that dies after the wipe, and three of the scripts are outside any role.

## Assumptions

- **Claim:** The key that signs `bats-core`'s release tags, and the one that signs `bats-assert`'s, can be obtained and its fingerprint confirmed from a source other than the repositories (the tags name key ID `3561E98F5A6BCA770F8E13BEE49BC732E729C954`).
  **Breaks if wrong:** Neither entry can be *signed*; both fall to *unsigned*, pinned by SHA only, which catches a moved pin and nothing else.
  **Checked by:** Fetching the maintainer's published key, comparing its fingerprint with the tags' key ID, and running `git verify-tag` against a keyring that holds only that key.
- **Claim:** A Renovate regex manager on the `github-tags` datasource can write a tag and its commit SHA together into the pin file.
  **Breaks if wrong:** Bumps are made by hand, and a pin goes stale without a pull request to say so.
  **Checked by:** A Renovate dry run on a branch that holds the pin file.

## Consequences

- A second test runner, three pins and the Renovate pull requests that move them.
- A stub encodes the argument shape of the tool it replaces. If the real tool's interface changes, the stub keeps passing; Molecule and the boot tests remain the checks against the real tools.
- Bats evaluates a test file more than once, so setup stays in `setup`, not at file level. `bats-core` 1.14 makes `run` honor `set -e` in the functions it calls, and exits non-zero when it finds no tests, so the job's path filter has to keep it from starting on a change with no suite behind it.
- The suite runs serially. A prototype of 30 tests across six scripts took about five seconds.
- The shell tests need Git and GitHub access to fetch the pins; the cloned trees are about 4 MB.
- A test runs the commands a script does not stub (`date`, `stat`, `tar`, `ls`, `find`, `du`) on the runner's userland, so a host on a different release from the runner can behave differently from the test.
- A test of a templated script renders it outside Ansible, so a template change that only Ansible's own rendering would expose is caught by Molecule, not here.

## Invariants

- The three cloned trees are the commits the pin file names; a mismatch fails before any test runs.
- No shell test calls a real external tool: each is either stubbed by the test or stubbed to fail.
- No shell test writes outside its own temporary directory.
- A negated assertion in a shell test is `run !`.

## Non-goals

- Behavior against the real services a script drives.
- A script's output layout or wording beyond what a test asserts.
- Python code, which stays under pytest.
- Rewriting a script to make it easier to test.
- A coverage threshold for shell.

## Validation

- The `shell-tests` job runs every Bats file on each pull request that changes a shell script, a shell test or the pin file.
- The pin check fails a pull request whose pin is not the commit a verified tag points at, and runs weekly like the other pin checks.
- The existing `shellcheck` hook reads the `.bats` files and flags a bare `!`.

## Reconsideration triggers

- `bats-core` stops publishing releases, or a Bash release breaks a pinned version.
- The `bats/bats` image, or one the repo builds, carries a signature or attestation ADR 0084 can verify, and its busybox userland gives the same results as the hosts' for the commands the scripts run.
- The scripts under test are rewritten in Python.
- Maintaining the pins costs more than the tests save.
