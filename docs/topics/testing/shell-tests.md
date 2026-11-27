# CI Shell Tests

Bats tests for the shell scripts that decide an outcome worth protecting: what a failed run leaves running or stopped, what is cleaned up on every exit path, what a prompt must be answered with. The decision is [ADR 0086 (Shell script tests)](../../decisions/0086-testing-the-control-flow-of-shell-scripts/revision-000.md). The runner and its libraries are the pinned clones described in [CI Shell Test Pins](shell-test-pins.md).

The tests are under [`tools/tests/shell/`](../../../tools/tests/shell), one `.bats` file per script. Each file's `@test` names state its assertions in full.

| Test file | Script | Asserts |
| :--- | :--- | :--- |
| `run_restore.bats` | [`run_restore.sh`](../../../docker/minecraft/scripts/run_restore.sh) | Step order; which failures leave the stack stopped; both prompts, and `-y`/`--yes`. |
| `run_upgrade.bats` | [`run_upgrade.sh`](../../../docker/minecraft/scripts/run_upgrade.sh) | The version, given or default, reaches compose; compose's exit status is the script's. |
| `snapshot_push.bats` | [`snapshot-push.sh`](../../../tools/openbao_utils/scripts/snapshot-push.sh) | Token revoked and scratch removed on every exit; secrets never in arguments; both providers attempted. |
| `snapshot_pull.bats` | [`snapshot-pull.sh`](../../../tools/openbao_utils/scripts/snapshot-pull.sh) | R2 then B2 fallback; hidden credential input; nothing left behind on failure. |
| `state_copy_push.bats` | [`state-copy-push.sh`](../../../tools/tofu_state/state-copy-push.sh) | Only ciphertext is pushed, by copy; R2 and B2 credentials stay apart; scratch removed on failure. |
| `molecule_test_all.bats` | [`molecule-test-all.sh`](../../../ansible/scripts/molecule-test-all.sh) | `-s` needs exactly one role; a role stops at its first failure, others still run; what `-j` runs at once and in what order; timings output. |
| `fetch_image.bats` | [`fetch_image.sh`](../../../tofu/modules/proxmox_opnsense_vm/fetch_image.sh) | Unpacked only when the checksum matches; a failed download or mismatch leaves no image. |
| `build_seed.bats` | [`build_seed.sh`](../../../tofu/modules/proxmox_opnsense_vm/seed/build_seed.sh) | Disk layout; owner-only seed; a failed build leaves no configuration behind. |
| `first_boot.bats` | [`first_boot.sh`](../../../tofu/modules/proxmox_opnsense_vm/first_boot/first_boot.sh) | Order of steps; password on stdin only; scratch removed; seed disk detached after success only. |
| `scratch_gateway.bats` | [`scratch_gateway.sh`](../../../tofu/scratch/opnsense/scratch_gateway.sh) | Refusals before `up`; no credential on a command line; what `down` removes and keeps. |
| `stage_image.bats` | [`stage_image.sh`](../../../tofu/scratch/opnsense/stage_image.sh) | Checksum, free space and leftovers when staging an image. |
| `acceptance.bats` | [`acceptance.sh`](../../../tofu/scratch/opnsense/acceptance/acceptance.sh) | The gateway and probe address are removed on every outcome; a failed check fails the run. |
| `prepare_image.bats` | [`prepare_image.sh`](../../../tofu/modules/proxmox_ubuntu_template/prepare_image.sh) | dracut changes are verified; unmount and detach on every exit; bad input writes nothing. |
| `retire_vm.bats` | [`retire_vm.sh`](../../../tools/rebuild_check/scripts/retire_vm.sh) | The guards on dump, destroy, drop-dump and restore. |
| `gateway_preflight.bats` | [`gateway_preflight.sh`](../../../tools/rebuild_check/scripts/gateway_preflight.sh) | Which findings fail or only note, before and during a gateway rebuild. |
| `move_vm_nic.bats` | [`move_vm_nic.sh`](../../../tools/rebuild_check/scripts/move_vm_nic.sh) | Keeps model and MAC; refuses a wrong VM or NIC before setting anything. |
| `check_freshness.bats` | template [`check-freshness.sh.j2`](../../../ansible/roles/backup_agent/templates/check-freshness.sh.j2) | Pushes only when every app is fresh; credentials never in arguments. |
| `caddy_cert_expiry.bats` | template [`check.sh.j2`](../../../ansible/roles/caddy_cert_expiry/templates/check.sh.j2) | Threshold boundary, expired or missing certificate, SNI. |
| `harness.bats` | The harness itself | Stubs fail by default, even when a script swallows the failure. |

A stub encodes the argument shape of the tool it replaces, so a change to a real tool's interface passes here and is caught only by Molecule or the boot test.

## Running them

From the repository root, install the locked environment, fetch the pinned clones once and point Bats at them:

```bash
uv sync --group dev --locked
```

```bash
CLONES=$(mktemp -d)
(cd tools && python3 -m ci.shell_tests.fetch "$CLONES")
```

```bash
BATS_LIB_PATH="$CLONES" "$CLONES/bats-core/bin/bats" tools/tests/shell
```

`CLONES` is any directory the fetch may fill. The runner is the fetched `bats-core`, and `BATS_LIB_PATH` is where `bats_load_library` finds `bats-support` and `bats-assert`. The suite needs Bash, GNU coreutils and `uv`, as the hosts and the runner have, and no network once the clones and the environment exist.

## In CI

The `shell-tests` job of `pr-checks.yml` runs when a pull request changes a shell script or `.sh.j2` template, a file under `tools/tests/shell/` or `tools/ci/shell_tests/`, or `tools/ci/verification.py` (the `shell_tests` output in [Change scoping](../engineering/ci/change-scoping.md#change-scoped-not-a-full-sweep)). It runs on the runner's own Bash and GNU userland, with the locked environment for the templates and `python3` for the fetch. It is not a matrix job, so it can be required directly: a pull request that changes none of those paths reports it skipped.

Its steps, in order:

1. Look for a `.bats` file under `tools/tests/shell/`. `bats-core` 1.14 exits non-zero when it finds no test, and the path filter can't tell a change with no suite behind it from one with, so with no `.bats` file the job ends with a notice and the steps below are skipped.
2. When the pin file or the tooling beside it changed, check each pinned tag with [`ci.shell_tests.pins`](shell-test-pins.md#checking-the-pins). A change to an unrelated script is not held to it, so a publisher moving a tag fails the weekly run rather than an unrelated pull request.
3. Install the locked environment with the `setup-uv-ansible` action, which restores the shared uv cache and never saves it. The tests render the `.sh.j2` templates with the Jinja2 in `uv.lock`, so the job waits for `warm-uv-cache` like the other jobs that restore it.
4. Fetch the pinned clones into the runner's temp directory with `ci.shell_tests.fetch`.
5. Run `bats` from the fetched `bats-core` over `tools/tests/shell` with `--print-output-on-failure`.

Any matching change runs every test file, not only the one for the script that changed.

## The harness

[`test_helper/harness.bash`](../../../tools/tests/shell/test_helper/harness.bash) is loaded by every test file, which calls `harness_setup` from `setup` and `harness_teardown` from `teardown`.

- **Fail-by-default stubs.** A directory of stubs comes first on `PATH`, with one for every external tool a script under test calls (`HARNESS_EXTERNAL_TOOLS`). Until a test replaces it with `stub`, a stub exits 127 and records the call, so a test that forgets one fails instead of running the real `docker`, `bao` or `ssh`. A script that swallows a failing command (`|| true`) would hide the forgotten stub from its exit status, so `harness_teardown` fails the test when any unstubbed call was recorded. A tool a script starts to call is added to the list.
- **Stubs that record.** `stub NAME` writes an executable that appends its arguments, one line, to the call log and then runs the body the test gives it. `calls_to NAME` reads the log back. A test makes a stub fail or succeed by what the body does, usually from an environment variable the test sets for one `run`.
- **The script is a copy.** `install_script PATH` copies a script from the repository into the test's own tree at the same relative path and prints the copy's path. The scripts find their files relative to themselves, so what they find is the test's directory and not the checkout.
- **Templates.** `render_template TEMPLATE VARIABLES_JSON` prints a `.sh.j2` template rendered by the Jinja2 locked in `uv.lock`, run through `uv run --frozen`. A variable the template uses and the test leaves out fails the render instead of becoming an empty string, so a template that starts to use a new variable fails its test until the test supplies it. The test redirects the output into a file and makes it executable. Molecule stays the authority on how Ansible itself renders the template.
- **Nothing outside the test directory.** `TMPDIR` and `HOME` point into the test's own directory, so a script's `mktemp -d` scratch directory lands there and is checked empty afterwards, and `GITHUB_STEP_SUMMARY` and `GITHUB_OUTPUT` are unset so a CI run's job summary is not appended to.

The commands a script runs that are not stubbed (`date`, `stat`, `tar`, `ls`, `find`, `du`) run on the machine's own userland.
