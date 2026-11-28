# Molecule Testing

Each role is tested in isolation with [Molecule](https://ansible.readthedocs.io/projects/molecule/), its scenarios under `ansible/roles/<role>/molecule/<scenario>/`. A scenario starts a real Docker container, converges the role into it, converges again to check idempotence, then verifies the result.

## Running scenarios

Each block starts at the repository root, with the [Python environment](../deploy/controller-setup.md#python-environment) activated. Set the names to the role and scenarios you want.

One scenario of one role:

```sh
role=compose scenario=volumes
(cd "ansible/roles/$role" && molecule test -s "$scenario")
```

Every scenario of one role:

```sh
role=compose
./ansible/scripts/molecule-test-all.sh "$role"
```

Several scenarios of one role (repeat `-s`):

```sh
role=compose
./ansible/scripts/molecule-test-all.sh "$role" -s reset -s build
```

Several scenarios at once, here four of them:

```sh
role=compose
./ansible/scripts/molecule-test-all.sh -j 4 "$role"
```

Every scenario of every role:

```sh
./ansible/scripts/molecule-test-all.sh
```

`molecule-test-all.sh` runs one `molecule test -s <scenario>` at a time from each role's directory, in name order, and stops a role at its first failure. With `-j N` it runs N at once, across roles too, on the one Docker daemon: every scenario's dependencies are installed first, one at a time, each scenario's output is printed whole when it ends, and a failure starts no further scenario of that role. CI does not use `-j`. The step-ca and OpenBao helpers a scenario starts are named from its role and scenario (`step-ca-<role>-<scenario>`, `openbao-<role>-<scenario>`, with host directories to match; [`vars/helper_names.yml`](../../../ansible/roles/molecule_helpers/vars/helper_names.yml) derives them, and the helpers take the names as variables), so the `secrets` scenarios run side by side. The scenarios of the other roles still start a helper under a fixed container name, network or host directory (`step-ca-test`, `openbao-test`, `lldap-test`, `seaweedfs-test`, and the shared `caddy-proxy` network), so scenarios that start the same one cannot run side by side: one removes or reuses the other's. Use `-j` for `secrets` and for roles that start none, such as `compose`, `compose_app`, `bind9` and `caddy`. `molecule test --all` from `ansible/` does not work: Molecule's scenario glob does not reach `roles/*/molecule/*/`, and a recursive glob rejects the many scenarios named `default` as duplicates.

The script prints a table of seconds per scenario, which CI also puts in the job summary and which shows whether a role is worth splitting across runners. With `MOLECULE_TIMINGS_FILE` set it writes the same rows, tab-separated, to that file for [the scheduled timing run](molecule-timings.md), and refuses `-j`, since times taken side by side are not comparable.

## Scenario matrix

One line per scenario. What exactly each one asserts is in its `verify.yml` and, for refusals, its `converge.yml`.

| Role | Scenario(s) | What it covers |
| :--- | :--- | :--- |
| `apt` | `default` | Package updates, with no systemd or privileged mode. |
| `fwupd` | *(none)* | Needs real firmware and LVFS hardware. |
| `docker` | `default` | Engine install; `no-new-privileges` and log rotation defaults reach a new container; a `daemon.json` key the role does not own survives. |
| `host_hardening` | `default` | Platform assertion, and unattended security updates read back from the effective apt configuration. |
| `cd_agent` | `default` | Fixture jobs run for real as their own users: what ran, job isolation, successor chains, timers, installed tools and the `sshd` restriction. |
| | `invalid_input` | Each bad input is refused by the check that names it, before the host is touched. |
| `qemu_guest_agent` | `default` | Package install, and the shipped unit still has the udev-activated shape ([`qemu-guest-agent.md`](../infra/qemu-guest-agent.md)). |
| `tailscale_node` | `default` | A logged-out node joins with a key and tag; the vendor apt source is replaced, forwarding is on and the key is left in no file. |
| | `client_node` | A node that advertises nothing: the earlier forwarding drop-in is removed and only DNS and auto-update are set. |
| | `drift` | A check run reports a hand change and applies nothing, and the next run repairs it. Starts with the daemon down. |
| | `no_key` | A logged-out node with no key is refused before anything is installed. |
| `compose` | `default` | Init and deploy happy path. |
| | `volumes` | Named-volume creation, config seeding with owner and mode kept, teardown. |
| | `scripts` | Both script deployment paths: direct copy and volume-seeded. |
| | `mounted_files` | A changed read-only mounted config and script recreate the service that mounts them and no other, also on the run after one that failed before deploying; a second run changes nothing; an app with no such mount has no override file. |
| | `build` | The `build: true` deploy branch. |
| | `cleanup` | `cleanup.yaml` dry run, keep-content path and label-fallback teardown. |
| | `reset` | A reset restores seeded config, discards runtime state, and refuses without confirmation. |
| `compose_app` | `default` | Batch run of `compose/` across apps. |
| | `strict` | `compose_app_continue_on_error: false`. |
| | `continue_on_error` | One broken app is reported while the healthy ones still deploy. |
| `secrets` | `default` | Generates `hex` and `uuid4` entries once and reads `manual` ones; formats and `0600` modes. |
| | `manual_missing` | A `manual` entry with no cache file fails, naming the secret. |
| | `vault_approle_missing` | Blank AppRole credential files fail before OpenBao is contacted. |
| | `vault_approle_files_missing` | Absent AppRole credential files fail through their own check. |
| | `cache_dir_env` | `HOMELAB_SECRETS_DIR` chooses the cache directory, and a relative value is refused. |
| | `delivered_root_cert` | A delivered root certificate that differs from the fetched one fails, naming the file. |
| | `vault_manual_missing` | A real AppRole login, then a failure for a `manual` secret never written to OpenBao. |
| | `vault_backed` | Against real OpenBao: create then reuse, checked by KV version; concurrent creators; no value in `-vvv` output; no `delete` on `hosts/*`. |
| | `rotate_secret` | Runs the real `rotate-secret.yaml`: each value changes and its KV version rises by exactly one. |
| | `snapshot_restore` | The [restore drill](../security/openbao/backup-restore.md) on a second node. Runs on every bump of the OpenBao pin. |
| `caddy` | `default` | Custom Caddy build and deploy; a `read_only: true` route proxies reads and answers writes with 405. |
| | `unregistered` | Without the Compose app, config renders and the image builds but nothing deploys. |
| `caddy_cert_expiry` | `default` | The check script against a live TLS handshake, the Gatus push config, and the `OnFailure=` alert for an unknown name. |
| | `no_routed_apps` | A host with no `caddy:` route fails, naming what is missing. |
| `telegram_notify` | *(none)* | Library role, covered through the roles that include it. |
| `opnsense_gateway` | *(none)* | Needs a gateway API. `ansible/tests/test_opnsense_pin.py` and `test_opnsense_policy.py` check the collection pin and zones. |
| `telegram_topic_pins` | *(none)* | Runs only on the control node (`pin-telegram-topics.yaml`). |
| `gatus_push` | *(none)* | Library role, covered through the roles that include it. |
| `systemd_reload` | *(none)* | Library role, covered through the roles that include it. |
| `bind9` | `default` | Zone rendering and reload with no secondary: transfers refused, no key rendered. |
| | `secondary` | Primary and secondary: keyed transfers only, matching serials, and a new record arrives without a restart. |
| | `invalid_host_records` | Each bad host record is refused by the check that names it, and valid edge cases pass. |
| `seaweedfs_bucket` | `default` | Creates a missing bucket; a plain delete leaves no version or delete marker, so a prune frees space. |
| | `wrong_credentials` | Bad credentials fail at once instead of being retried. |
| | `identity_scoping` | The production `s3-identity.json.j2`: each host reaches only its own prefix, and the cloud-sync reader cannot write. |
| `step_ca_client` | `default` | The cached root certificate matches the CA's byte for byte. |
| | `not_running` | No step-ca: the first guard fails. |
| `step_ca_cert` | `default` | First certificate for lldap on an empty volume, recovery from its crash loop, and the renewal unit's commands and effects. |
| | `renewal_timing` | The timer skips a certificate that is not due and renews one that is. |
| | `signal_chown` | OpenBao: ownership returns to `openbao` and the listener serves the renewed certificate without a restart. |
| | `not_running` | No target container: fails before anything touches step-ca. |
| | `san_drift` | A certificate for other names fails with the reissue command and is left unchanged. |
| | `probe_fails` | A probe that cannot run stops the role instead of issuing over a certificate. |
| `lldap_bootstrap` | `default` | Creates the observer account in `lldap_strict_readonly`. |
| | `not_running` | No lldap: the guard fails before anything else. |
| `openbao` | `data_chown` | The data volume chown reaches the whole subtree with modes kept, and is skipped when the top directory already matches. |
| `openbao_cli` | `default` | Pinned `.deb` install, version matching the server, TLS `bao status`, and the server unit masked. |
| | `not_running` | No `openbao` container: fails before downloading anything. |
| `tinyauth` | `default` | Real tinyauth binds to a throwaway lldap and reports healthy. |
| `tinyauth_ca_trust` | `default` | tinyauth with `tinyauth_ldap_insecure: false` trusts lldap's step-ca certificate ([`lldap.md`](../services/lldap.md)). |
| | `not_running` | No tinyauth: the guard fails before any CA bundle work. |
| `backup_agent` | `default` | Per-app schedules and stop labels, encrypted archives that decrypt, least-capability volume reads, the Docker API proxy rules call by call, stale-schedule removal and the freshness push. |
| | `no_stop_apps` | With no app to stop, no Docker API proxy or rules file is rendered; a changed schedule recreates the agent. |
| | `varying_cron` | Different cron cadences give different freshness thresholds, from the longest gap. |
| `cloud_sync` | `default` | Syncs each host's apps to their cloud targets; the job's real side effects, and repair of hand-edited units. |
| `restore` | `default` | Stop, extract, overwrite, redeploy, with the archive's owners and modes. |
| | `multi_volume` | Several volumes from one archive, ignoring a decoy and another app. |
| | `uncompressed_archive` | The same restore from a plain `.tar`. |
| | `validation_failure` | A missing or unreadable archive blocks every destructive step. |
| | `confirmation_declined` | `restore_confirm: false` blocks every destructive step. |
| `restore_discovery` | `default` | Manifest and `rclone.conf` content and order from synthetic input. |
| | `discovery_and_restore` | `restore_all.py` picks the newest object and falls over to a cloud target, with real S3 and GPG. |

Beyond Docker, `cd_agent`'s and `openbao_cli`'s `default` need network access to GitHub, and `backup_agent`'s `default` needs `gpg` on the controller.

The scaffolding the scenarios share, in `molecule_helpers`, and how its Docker-in-Docker containers work are in [`molecule-fixtures.md`](molecule-fixtures.md).

## Idempotence exceptions

These scenarios have no `idempotence` step:

| Why | Scenarios |
| :--- | :--- |
| Every run is a refusal the scenario expects | `bind9/invalid_host_records`, `cd_agent/invalid_input`, `tailscale_node/no_key`, `secrets/{manual_missing, vault_manual_missing, vault_approle_missing, vault_approle_files_missing, cache_dir_env, delivered_root_cert}` |
| What it runs is meant to change something every time | `restore/{default, multi_volume, uncompressed_archive}`, `secrets/{rotate_secret, snapshot_restore}` |
| Its setup makes new data every run | `restore/confirmation_declined`, `restore_discovery/discovery_and_restore` |
| It waits out a real certificate lifetime | `step_ca_cert/renewal_timing` |
| Its check run reports a difference every time | `tailscale_node/drift` |

Two more are narrower than they look:

- `lldap_bootstrap`'s bootstrap block is tagged `molecule-idempotence-notest`, because it creates and removes the same `/tmp` file on every run. Idempotence therefore does not re-run it, and `bootstrap.sh`'s own idempotency is not checked live.
- `cloud_sync`'s step covers only rendering. A oneshot sync reports changed each time it fires, so `verify.yml` triggers it separately; `side_effect.yml` then edits the notifier and push units by hand and checks that a converge puts them back.

## What a pass does not show

| Scenario | Limit |
| :--- | :--- |
| `tailscale_node` | The client is a stub answering from a state file, since a join needs a control plane. Its preference keys and values are those recorded in [`network-infra.md`](../infra/network-infra.md); real `tailscaled` runs but nothing talks to it. |
| `cloud_sync` | SeaweedFS stands in for R2, B2 and OCI, whose credentials CI does not have. |
| `caddy_cert_expiry` | The internal CA's certificates are too short-lived for the production threshold, so the live pass uses `caddy_cert_expiry_threshold_days: 0`. |
| `step_ca_cert/default` | Runs the renewal commands directly; only `renewal_timing` exercises the timer's `needs-renewal` gate. |
| `host_hardening`, `qemu_guest_agent` | Service tasks do not run in these containers. |

## Writing assertions

A scenario asserts the side effect, not the exit code ([`AGENTS.md`](../../../AGENTS.md#verification-before-writing-it-down)): a container's `StartedAt`, a volume's content, a KV version.

A negative-path scenario asserts on `ansible_failed_task` and `ansible_failed_result` (the task name and a distinctive part of the message), not on a bare `rescue:` firing, which cannot tell the expected failure from an unrelated one such as Docker not being ready. Copy the pattern in [`restore/molecule/validation_failure/converge.yml`](../../../ansible/roles/restore/molecule/validation_failure/converge.yml).

`backup_agent`'s `default` splits its assertions across `verify_*.yml` files, because its fixture is too expensive to stand up more than once.

## Adding a new scenario

1. Copy an existing scenario directory, such as `compose/molecule/default` for anything deployed with Compose.
2. For Docker-in-Docker, use `ghcr.io/wenenhoe/molecule-dind:latest@sha256:…` as the platform `image:`, with the digest from an existing scenario, and point `prepare` at `molecule_helpers/playbooks/prepare_dind_prebuilt.yml`. Docker is running once the container boots, so `converge.yml` does not install it. The exceptions are `docker` (it tests the install) and `bind9` ([why](molecule-fixtures.md#pre-baked-dind-image)).
3. If the role uses `app_catalog` or `compose_apps`, point `converge.yml` at `molecule_helpers`' `resolve_compose_apps.yaml` and read `resolved_apps`. Then, as the role needs:

   | The role reads | In the scenario |
   | :--- | :--- |
   | its own host's `backup_plan` | define `backup_defaults`, and run `resolve_backup_plan.yaml` after `resolve_compose_apps.yaml` |
   | other hosts' `resolved_apps` (hosts built with `add_host`) | set each one with `\| resolve_apps(app_catalog)` |
   | other hosts' `backup_plan` | define `backup_defaults`, and give each `add_host` host `backup_plan: "{{ ... \| resolve_apps(app_catalog) \| backup_plan(backup_defaults) }}"` |
   | `backup_hosts`, itself or through the SeaweedFS identity file | after the `add_host`, `set_fact` it from `groups['<group>'] \| backup_hosts(hostvars)`; each such host needs a non-empty `backup_plan` |

4. Add no `dependency.options` or `provisioner.env` block: the base config supplies both.
5. Add the scenario's row to the [matrix](#scenario-matrix), and to [Idempotence exceptions](#idempotence-exceptions) if it has no such step.
6. Run every scenario of the role locally before opening a pull request, so [its coverage floor](#coverage) is checked too. CI also runs every role whose watch set the pull request touches ([`ci/change-scoping.md`](../engineering/ci/change-scoping.md#change-scoped-not-a-full-sweep)).

## Coverage

CI holds each tested role to a floor of task coverage, so a new task, loop or `when:` needs a scenario that runs it ([`ci/gates.md`](../engineering/ci/gates.md#molecule-coverage-gate)). `molecule-test-all.sh` without `-s` applies the same floor to each role whose scenarios all passed, from that run's data, and fails on a role under it. With `-s` it says that coverage was not checked. [`molecule-coverage/README.md`](../../../ansible/molecule-coverage/README.md) describes the report.

## What molecule scenarios can't catch: tag wiring

Every `converge.yml` calls its role directly (`include_role: name:
bind9`), never through `deploy.yaml`, so the `images`/`infra` tag scheme
(see [`deployment-flow.md`](../deploy/deployment-flow.md#tags)) is invisible to
these scenarios — nothing here exercises `deploy.yaml`'s own `Include
<role>` wrapper tasks that `--tags images` actually depends on. A
refactor that renames a task or swaps `include_role` for `import_role` in
that chain could break `--tags images`/`--tags infra` silently. Verify
manually before trusting a change to it:

```sh
# paste alone, from ansible/; it waits for the host to try
read -r -p 'host: ' host && ansible-playbook playbooks/deploy.yaml --tags images --limit "$host,localhost" -vvv | grep "TASK \["
```

and confirm only the expected tasks show up.
