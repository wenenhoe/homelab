# CI Shell Tests

Bats tests for the shell scripts that decide an outcome worth protecting: what a failed run leaves running or stopped, what is cleaned up on every exit path, what a prompt must be answered with. The decision is [ADR 0086 (Shell script tests)](../../../decisions/0086-testing-the-control-flow-of-shell-scripts/revision-000.md). The runner and its libraries are the pinned clones described in [CI Shell Test Pins](shell-test-pins.md).

The tests are under [`tools/tests/shell/`](../../../../tools/tests/shell/), one `.bats` file per script:

| Test file | Script |
| :--- | :--- |
| `run_restore.bats` | [`docker/minecraft/scripts/run_restore.sh`](../../../../docker/minecraft/scripts/run_restore.sh) |
| `snapshot_push.bats` | [`tools/openbao_utils/scripts/snapshot-push.sh`](../../../../tools/openbao_utils/scripts/snapshot-push.sh) |
| `molecule_test_all.bats` | [`ansible/scripts/molecule-test-all.sh`](../../../../ansible/scripts/molecule-test-all.sh) |
| `run_upgrade.bats` | [`docker/minecraft/scripts/run_upgrade.sh`](../../../../docker/minecraft/scripts/run_upgrade.sh) |
| `fetch_image.bats` | [`tofu/modules/proxmox_opnsense_vm/fetch_image.sh`](../../../../tofu/modules/proxmox_opnsense_vm/fetch_image.sh) |
| `build_seed.bats` | [`tofu/modules/proxmox_opnsense_vm/seed/build_seed.sh`](../../../../tofu/modules/proxmox_opnsense_vm/seed/build_seed.sh) |
| `first_boot.bats` | [`tofu/modules/proxmox_opnsense_vm/first_boot/first_boot.sh`](../../../../tofu/modules/proxmox_opnsense_vm/first_boot/first_boot.sh) |
| `scratch_gateway.bats` | [`tofu/scratch/opnsense/scratch_gateway.sh`](../../../../tofu/scratch/opnsense/scratch_gateway.sh) |
| `stage_image.bats` | [`tofu/scratch/opnsense/stage_image.sh`](../../../../tofu/scratch/opnsense/stage_image.sh) |
| `prepare_image.bats` | [`tofu/modules/proxmox_ubuntu_template/prepare_image.sh`](../../../../tofu/modules/proxmox_ubuntu_template/prepare_image.sh) |
| `acceptance.bats` | [`tofu/scratch/opnsense/acceptance/acceptance.sh`](../../../../tofu/scratch/opnsense/acceptance/acceptance.sh) |
| `check_freshness.bats` | the template [`check-freshness.sh.j2`](../../../../ansible/roles/backup_agent/templates/check-freshness.sh.j2) |
| `caddy_cert_expiry.bats` | the template [`check.sh.j2`](../../../../ansible/roles/caddy_cert_expiry/templates/check.sh.j2) of the `caddy_cert_expiry` role |
| `harness.bats` | the harness itself |

## Running them

From the repository root, install the locked environment, fetch the pinned clones once and point Bats at them:

```bash
uv sync --group dev --locked
(cd tools && python3 -m ci.shell_tests.fetch "$CLONES")
BATS_LIB_PATH="$CLONES" "$CLONES/bats-core/bin/bats" tools/tests/shell
```

`CLONES` is any directory the fetch may fill. The runner is the fetched `bats-core`, and `BATS_LIB_PATH` is where `bats_load_library` finds `bats-support` and `bats-assert`. The suite needs Bash, GNU coreutils and `uv`, as the hosts and the runner have, and no network once the clones and the environment exist.

## In CI

The `shell-tests` job of `pr-checks.yml` runs when a pull request changes a shell script or `.sh.j2` template, a file under `tools/tests/shell/` or `tools/ci/shell_tests/`, or `tools/ci/verification.py` (the `shell_tests` output in [Change scoping](change-scoping.md#change-scoped-not-a-full-sweep)). It runs on the runner's own Bash and GNU userland, with the locked environment for the templates and `python3` for the fetch. It is not a matrix job, so it can be required directly: a pull request that changes none of those paths reports it skipped.

Its steps, in order:

1. Look for a `.bats` file under `tools/tests/shell/`. `bats-core` 1.14 exits non-zero when it finds no test, and the path filter can't tell a change with no suite behind it from one with, so with no `.bats` file the job ends with a notice and the steps below are skipped.
2. When the pin file or the tooling beside it changed, check each pinned tag with [`ci.shell_tests.pins`](shell-test-pins.md#checking-the-pins). A change to an unrelated script is not held to it, so a publisher moving a tag fails the weekly run rather than an unrelated pull request.
3. Install the locked environment with the `setup-uv-ansible` action, which restores the shared uv cache and never saves it. The tests render the `.sh.j2` templates with the Jinja2 in `uv.lock`, so the job waits for `warm-uv-cache` like the other jobs that restore it.
4. Fetch the pinned clones into the runner's temp directory with `ci.shell_tests.fetch`.
5. Run `bats` from the fetched `bats-core` over `tools/tests/shell` with `--print-output-on-failure`.

Any matching change runs every test file, not only the one for the script that changed.

## The harness

[`test_helper/harness.bash`](../../../../tools/tests/shell/test_helper/harness.bash) is loaded by every test file, which calls `harness_setup` from `setup` and `harness_teardown` from `teardown`.

- **Fail-by-default stubs.** A directory of stubs comes first on `PATH`, with one for every external tool a script under test calls (`HARNESS_EXTERNAL_TOOLS`). Until a test replaces it with `stub`, a stub exits 127 and records the call, so a test that forgets one fails instead of running the real `docker`, `bao` or `ssh`. A script that swallows a failing command (`|| true`) would hide the forgotten stub from its exit status, so `harness_teardown` fails the test when any unstubbed call was recorded. A tool a script starts to call is added to the list.
- **Stubs that record.** `stub NAME` writes an executable that appends its arguments, one line, to the call log and then runs the body the test gives it. `calls_to NAME` reads the log back. A test makes a stub fail or succeed by what the body does, usually from an environment variable the test sets for one `run`.
- **The script is a copy.** `install_script PATH` copies a script from the repository into the test's own tree at the same relative path and prints the copy's path. The scripts find their files relative to themselves, so what they find is the test's directory and not the checkout.
- **Templates.** `render_template TEMPLATE VARIABLES_JSON` prints a `.sh.j2` template rendered by the Jinja2 locked in `uv.lock`, run through `uv run --frozen`. A variable the template uses and the test leaves out fails the render instead of becoming an empty string, so a template that starts to use a new variable fails its test until the test supplies it. The test redirects the output into a file and makes it executable. Molecule stays the authority on how Ansible itself renders the template.
- **Nothing outside the test directory.** `TMPDIR` and `HOME` point into the test's own directory, so a script's `mktemp -d` scratch directory lands there and is checked empty afterwards, and `GITHUB_STEP_SUMMARY` and `GITHUB_OUTPUT` are unset so a CI run's job summary is not appended to.

The commands a script runs that are not stubbed (`date`, `stat`, `tar`, `ls`, `find`, `du`) run on the machine's own userland.

`harness.bats` proves the stubs fail by default, that a test whose script swallows the failure still fails, and that a stubbed tool passes, by running a second Bats over a generated test file.

## What each file asserts

- **`run_restore.bats`**: the order of the restore's steps; that a failure after the data directory was emptied leaves the stack stopped and one before it starts the stack again; and that both prompts are honored, `-y` and `--yes` skip them, and the first wants `yes` and the second `delete`.
- **`snapshot_push.bats`**: that the token is revoked and the scratch directory removed on every exit path that has one; that the `secret_id` reaches the login as a file without its newline and never as an argument, whether cached or prompted; that `rclone.conf` is mode 0600 and pairs each provider with its own credentials; and that R2 and B2 are both attempted when one push fails, with the failure named.
- **`molecule_test_all.bats`**: that `-s` is refused unless exactly one role is named; that each scenario runs on its own in name order against the base config; that a role stops at its first failed scenario without stopping the other roles; and that the timings table is printed and appended to the job summary only when there is one.

- **`run_upgrade.bats`**: that the version argument, or the default without one, reaches the compose run in the script's own directory; and that the compose run's exit status is reported and is the script's own.
- **`fetch_image.bats`**: that a download matching the published checksum is unpacked next to itself in a cache directory that did not exist; that the download is one `curl` of the URL into that directory; that a mismatch removes the download and leaves no unpacked image, naming the URL and both checksums; and that a failed download stops with curl's status before anything is unpacked.
- **`prepare_image.bats`**: that the omission is in the image's dracut configuration before dracut regenerates, and dracut runs without host-only mode; that only the loop device's own partitions are asked for labels; that the mounts, the unmounts in reverse order and the loop detach happen on every exit path, and that a failed unmount keeps the work directory; that a checksum mismatch, an image without dracut, one without a root partition, one whose initramfs does not list the module, one whose initramfs still lists it after regeneration, and a listing that fails each fail with nothing written to the output directory; and that the output is the compressed qcow2 copy with its checksum beside it.
- **`check_freshness.bats`**: that one push is made when every app is fresh, none when one is stale (and the unit still succeeds), and none when `rclone` fails (and the unit fails, naming the app and the error); that with no push URL the apps are still checked; and that the credentials reach each container in a mode 0600 env file that is removed afterwards and never appear in an argument.
- **`caddy_cert_expiry.bats`**: that a certificate passes with more than and with exactly the threshold of days left and fails with fewer, expired, or none on the wire; and that the connection goes to loopback with the real hostname as the SNI.

A stub encodes the argument shape of the tool it replaces, so a change to a real tool's interface passes here and is caught only by Molecule or the boot test.
