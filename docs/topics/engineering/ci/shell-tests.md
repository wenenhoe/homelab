# CI Shell Tests

Bats tests for the shell scripts that decide an outcome worth protecting: what a failed run leaves running or stopped, what is cleaned up on every exit path, what a prompt must be answered with. The decision is [ADR 0086 (Shell script tests)](../../../decisions/0086-testing-the-control-flow-of-shell-scripts/revision-000.md). The runner and its libraries are the pinned clones described in [CI Shell Test Pins](shell-test-pins.md).

The tests are under [`tools/tests/shell/`](../../../../tools/tests/shell/), one `.bats` file per script:

| Test file | Script |
| :--- | :--- |
| `run_restore.bats` | [`docker/minecraft/scripts/run_restore.sh`](../../../../docker/minecraft/scripts/run_restore.sh) |
| `snapshot_push.bats` | [`tools/openbao_utils/scripts/snapshot-push.sh`](../../../../tools/openbao_utils/scripts/snapshot-push.sh) |
| `harness.bats` | the harness itself |

## Running them

From the repository root, fetch the pinned clones once and point Bats at them:

```bash
(cd tools && python3 -m ci.shell_tests.fetch "$CLONES")
BATS_LIB_PATH="$CLONES" "$CLONES/bats-core/bin/bats" tools/tests/shell
```

`CLONES` is any directory the fetch may fill. The runner is the fetched `bats-core`, and `BATS_LIB_PATH` is where `bats_load_library` finds `bats-support` and `bats-assert`. The suite needs Bash and GNU coreutils, as the hosts have, and no network once the clones exist.

## The harness

[`test_helper/harness.bash`](../../../../tools/tests/shell/test_helper/harness.bash) is loaded by every test file, which calls `harness_setup` from `setup` and `harness_teardown` from `teardown`.

- **Fail-by-default stubs.** A directory of stubs comes first on `PATH`, with one for every external tool a script under test calls (`HARNESS_EXTERNAL_TOOLS`). Until a test replaces it with `stub`, a stub exits 127 and records the call, so a test that forgets one fails instead of running the real `docker`, `bao` or `ssh`. A script that swallows a failing command (`|| true`) would hide the forgotten stub from its exit status, so `harness_teardown` fails the test when any unstubbed call was recorded. A tool a script starts to call is added to the list.
- **Stubs that record.** `stub NAME` writes an executable that appends its arguments, one line, to the call log and then runs the body the test gives it. `calls_to NAME` reads the log back. A test makes a stub fail or succeed by what the body does, usually from an environment variable the test sets for one `run`.
- **The script is a copy.** `install_script PATH` copies a script from the repository into the test's own tree at the same relative path and prints the copy's path. The scripts find their files relative to themselves, so what they find is the test's directory and not the checkout.
- **Nothing outside the test directory.** `TMPDIR` and `HOME` point into the test's own directory, so a script's `mktemp -d` scratch directory lands there and is checked empty afterwards, and `GITHUB_STEP_SUMMARY` and `GITHUB_OUTPUT` are unset so a CI run's job summary is not appended to.

The commands a script runs that are not stubbed (`date`, `stat`, `tar`, `ls`, `find`, `du`) run on the machine's own userland.

`harness.bats` proves the stubs fail by default, that a test whose script swallows the failure still fails, and that a stubbed tool passes, by running a second Bats over a generated test file.

## What each file asserts

- **`run_restore.bats`**: the order of the restore's steps; that a failure after the data directory was emptied leaves the stack stopped and one before it starts the stack again; and that both prompts are honored, `-y` and `--yes` skip them, and the first wants `yes` and the second `delete`.
- **`snapshot_push.bats`**: that the token is revoked and the scratch directory removed on every exit path that has one; that the `secret_id` reaches the login as a file without its newline and never as an argument, whether cached or prompted; that `rclone.conf` is mode 0600 and pairs each provider with its own credentials; and that R2 and B2 are both attempted when one push fails, with the failure named.

A stub encodes the argument shape of the tool it replaces, so a change to a real tool's interface passes here and is caught only by Molecule or the boot test.
