---
id: PROJ-shell-script-tests
title: "Shell Script Tests"
type: project
status: building
blocked: false
summary: "Unit-test the branching and cleanup of the repo's shell scripts with Bats, from pinned clones of bats-core, bats-support and bats-assert, in a scoped CI job."
decision: ADR-0086/0
allowed_paths:
  - tools/ci/shell_tests/**
  - tools/tests/ci/shell_tests/**
  - tools/tests/ci/test_stdlib_only.py
  - tools/tests/ci/test_workflow_timeouts.py
  - tools/tests/shell/**
  - .github/workflows/pr-checks.yml
  - .github/workflows/check-shell-test-pins.yml
  - .github/detect-changes-filters.yml
  - .github/renovate.json5
  - docs/topics/engineering/ci/**
  - docs/topics/engineering/conventions.md
  - docs/topics/README.md
---

# Shell Script Tests

Adds Bats tests for the shell scripts that decide an outcome worth protecting, the pinned tooling they run on, and the CI job that runs them. It is staged because the pins and their check, the harness with its first tests, the CI wiring and the remaining scripts each ship and verify on their own, and the CI job needs a suite to run before it can be turned on.

## Scope

In: a stdlib-only `tools/ci/shell_tests` package with unit tests, holding the pin check and the fetch of the pinned clones; the pin file and its Renovate manager; the Bats harness under `tools/tests/shell/` with stubs that fail by default; test files for the scripts the decision names; a `shell-tests` job in `pr-checks.yml` and a weekly pin check; the docs for both and a "Shell tests" section in `conventions.md`.

Not in: changing a script to make it easier to test; Python tests; behavior against the real services a script drives, which Molecule and the boot test keep; a coverage threshold; scripts the decision leaves out until one is chosen.

## Decision

Implements [ADR 0086 (Shell script tests)](../decisions/0086-testing-the-control-flow-of-shell-scripts/revision-000.md), `approved`; this doc tracks build status only.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | The pins and their check | Done | A pin file lists `bats-core`, `bats-support` and `bats-assert` by repository, release tag and full commit SHA, one per line. `python3 -m ci.shell_tests.pins check` resolves each tag with `git ls-remote` and fails when it does not point at the pinned SHA, and `python3 -m ci.shell_tests.fetch DIR` clones each pin by SHA and refuses unless `HEAD` equals it. Unit tests cover an annotated tag, a lightweight tag, a moved tag, a missing tag, a malformed line, and a clone whose `HEAD` is not the pin, with `git` run against real local repositories. `test_stdlib_only.py` lists the new modules. A regex manager in `renovate.json5` matches every line of the pin file, asserted by a test |
| 2 | The harness and the first three scripts | Done | `tools/tests/shell/` holds a harness that puts a stub directory first on `PATH` and installs a stub that fails for every external tool a script under test calls, so a test that forgets one fails instead of running the real tool, and a test proves that. Test files for `run_restore.sh`, `snapshot-push.sh` and `molecule-test-all.sh` pass on the fetched clones, each ending in an assertion on an outcome the script decides, every negation written `run !`, and `shellcheck` passes on all of it. `run_restore.sh` is asserted to leave the stack stopped after a failure that follows the wipe and to restart it after one that does not, and to honor both prompts. `snapshot-push.sh` is asserted to revoke its token and remove its scratch directory on every exit path, never to put the `secret_id` in an argument, to write `rclone.conf` mode 0600, and to attempt B2 after an R2 failure. `molecule-test-all.sh` is asserted to refuse `-s` with other than one role, stop a role at its first failed scenario without stopping the others, and write the timings table |
| 3 | Run it in CI | Done | A `shell_tests` filter in `detect-changes-filters.yml` covers shell scripts, `.sh.j2` templates, `tools/tests/shell/**` and `tools/ci/shell_tests/**`. A `shell-tests` job in `pr-checks.yml` runs when it matches, on the runner's own Bash and Python with `python3 -m ci.shell_tests.fetch`, and does not start on a change with no suite behind it. `check-shell-test-pins.yml` runs the pin check weekly and on demand. `pipeline.md`'s Jobs table lists the job, the CI docs describe both, and `conventions.md` states the style, so `check-doc-drift` passes |
| 4 | The templated checks and `run_upgrade.sh` | Done | `check-freshness.sh.j2`, the Caddy certificate check and `run_upgrade.sh` have test files. The templates are rendered by Jinja2 with strict undefined variables. The freshness check is asserted to push once when every app is fresh, to suppress the push without failing when one is stale, to suppress it and fail when `rclone` fails, and to pass its credentials in a 0600 env file that is removed afterwards. The certificate check is asserted at, below and above the threshold, and to connect to loopback with the real hostname as the SNI. `run_upgrade.sh` is asserted to pass its version to the compose run and to report and propagate its exit status |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] Each of the three pins is checked against its release tag, and a pin whose tag does not resolve to its SHA fails the check.
- [ ] The clones the tests run on are the pinned commits, and a clone at any other commit is refused.
- [ ] A shell test that calls an external tool it did not stub fails, verified.
- [ ] Every test file named in stages 2 and 4 passes on the fetched clones under the runner's Bash.
- [ ] No shell test writes outside its own temporary directory.
- [ ] The `shell-tests` job runs on a pull request that changes a script covered by a test and does not run on one that changes none, verified.
- [ ] The weekly pin check runs on demand and passes.
- [ ] `pre-commit run --all-files` passes with the `.bats` files in the tree.

## Agent handoff

Stop conditions are in [`README.md#stop-conditions`](README.md#stop-conditions); they apply without being restated here.

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** the scripts under test; a script that cannot be tested without a change stops the work and goes to the maintainer. The linked revision's Decision.
- **Relevant files and interfaces:** the shell scripts listed in the decision; `tools/ci/checksums/` and `tools/ci/provenance/` for the shape of an existing pin check; `.github/workflows/check-release-checksums.yml` for the weekly workflow; `docs/topics/engineering/ci/pipeline.md` for the Jobs table that `check-doc-drift` reads.
- **Required checks:** `pre-commit run --all-files` with the hooks that need Docker or network skipped and named; `uv run pytest` from `tools/`; the Bats suite on the fetched clones, run on the pull request's own commit.

## Risks

- A stub encodes the argument shape of the tool it replaces, so a change to a real tool's interface passes here and is caught only by Molecule or the boot test.
- `bats-core` 1.14 changes how `run` treats `set -e` and exits non-zero on an empty suite; a version bump can change what a test means.
- A host on a different Ubuntu release from the runner can behave differently on the commands a test does not stub.
- If Renovate cannot supply a tag's SHA, bumps are made by hand and a pin can go stale without a pull request.

## Open items

- Whether a drift check should require every tracked shell script to have a test file or a stated reason for having none. The decision leaves the other scripts to be chosen one at a time.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
