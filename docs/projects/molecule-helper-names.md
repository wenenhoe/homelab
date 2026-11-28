---
id: PROJ-molecule-helper-names
title: "Molecule Helper Names"
type: project
status: not-started
blocked: false
summary: "Give every throwaway helper a Molecule scenario starts (step-ca, OpenBao, lldap, SeaweedFS) a name, network and host directory of its own per scenario, so scenarios can run side by side on one Docker daemon, and add a check that two scenarios cannot share one."
---

# Molecule Helper Names

Scenarios that start the same throwaway helper container give it one fixed name, so two of them running at once remove or reuse each other's helper. `molecule-test-all.sh -j N` runs scenarios side by side on one daemon, and it fails today for any set that holds two of them. This project makes each scenario's helpers its own. It is staged because the four helpers are shared by 20 or so scenarios in a dozen roles, and a half-renamed scenario cannot pass.

## Scope

In: the four `start_*_test_target.yaml` helpers in `ansible/roles/molecule_helpers/tasks/`; every scenario that starts one or names its container, network or host directory (the inventory below); a test that fails when two scenarios resolve to the same helper name, network, host directory or published port; the Molecule topic docs.

Not in: the scenario platform containers, whose instance names are already unique across roles; CI, which does not use `-j` and stays as it is; a CI workflow that times `-j` on a runner, which waits until a set of scenarios passes side by side here; the helpers' images and digests; capability sets, which [`molecule-container-hardening.md`](molecule-container-hardening.md) owns.

## Decision

None gates this: the work removes a collision and chooses no behaviour a reader of the code would not expect. How a scenario gets its names (a default derived from the scenario, or a name each one passes) is a design point settled in stage 1, under [Open items](#open-items).

## What collides

Found by running `secrets` with `-j 4` in a cloud session: 6 of its 10 scenarios passed and 4 failed, `rotate_secret`, `vault_backed`, `snapshot_restore` and `vault_manual_missing`. `rotate_secret` alone passed in 142 s, so the cause is not the session. The errors were `lookup step-ca-test ... no such host` and `error reading /certs/root_ca.crt: no such file or directory`: each of the four starts `step-ca-test` and `openbao-test` and mounts `/tmp/molecule-openbao-test-certs` and `-data`, so one's cleanup or start undoes another's. Memory, disk and CPU were not the limit (free memory stayed above 13.9 GB of 15 and disk use rose by about 1 GB).

What each helper fixes, and what is already a variable:

| Helper | Fixed today | Already a variable |
| :--- | :--- | :--- |
| `start_step_ca_test_target` | container `step-ca-test` and its DNS name | network |
| `start_openbao_test_target` | container `openbao-test`, also in its cert SANs, `api_addr`, `cluster_addr` and raft `node_id`; host directories `/tmp/molecule-openbao-test-certs` and `-data`; the `openbao-test-cert-issue` and `-chmod-certs` helper containers | network, published host port (the four `secrets` scenarios already use 18200 to 18203), step-ca container name |
| `start_lldap_test_target` | container `lldap-test`; host directory `/tmp/lldap-test-certs` | network |
| `start_seaweedfs_test_target` | container `seaweedfs-test`; host file `/tmp/seaweedfs-test-s3-identity.json` | network (optional) |

Scenarios that start each helper (their converge, verify and cleanup also write the names literally, 43 files in all):

- step-ca: `openbao/data_chown`, `openbao_cli/default`, `secrets/{rotate_secret,snapshot_restore,vault_backed,vault_manual_missing}`, `step_ca_cert/{default,renewal_timing,signal_chown}`, `step_ca_client/default`, `tinyauth_ca_trust/default`. `step_ca_client/not_running` and `lldap_bootstrap/not_running` start nothing: they assert that no container named `step-ca-test` or `lldap-test` is running, so they fail beside any scenario that has one up, and need a name that no other scenario can use.
- OpenBao: the same four `secrets` scenarios.
- lldap: `lldap_bootstrap/default`, `step_ca_cert/default`, `tinyauth/default`, `tinyauth_ca_trust/default`.
- SeaweedFS: `backup_agent/default`, `cloud_sync/default`, `restore_discovery/discovery_and_restore`, `seaweedfs_bucket/{default,identity_scoping,wrong_credentials}`.

The four `secrets` scenarios already use a network of their own (`secrets-<scenario>-net`). The others create and use one shared network, `caddy-proxy`, so two of them running at once also create, use and remove the same network. Nobody has run them side by side yet, so which of them fail together is unknown.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | The step-ca and OpenBao helpers, and the four `secrets` scenarios | Not started | The helpers take a container name and host directories that default to what they use today, so a scenario not yet changed behaves as before. The four scenarios derive their names from their own, and use them in converge, verify and cleanup. `uv run ./scripts/molecule-test-all.sh -j 4 secrets` passes all ten scenarios and so does the same run without `-j`, and the other roles that start these helpers pass in CI |
| 2 | The remaining step-ca and lldap consumers, and the shared network | Not started | Each scenario of `openbao`, `openbao_cli`, `step_ca_cert`, `step_ca_client`, `tinyauth`, `tinyauth_ca_trust` and `lldap_bootstrap` has helper names, a network and host directories of its own, and a run of those roles with `-j 4` passes |
| 3 | The SeaweedFS helper and its consumers | Not started | Each scenario of `backup_agent`, `cloud_sync`, `restore_discovery` and `seaweedfs_bucket` has a SeaweedFS name and identity file of its own, and a run of those roles with `-j 4` passes |
| 4 | The check and the docs | Not started | A test fails when two scenarios resolve to the same helper container, network, host directory or published port, and fails on a copy with one name made shared. The Molecule topic docs say a scenario's helpers are named from the scenario and that `-j` is safe |

Stage status is `Not started`, `In progress`, or `Done`. Stage 1 is one pull request: a half-renamed `secrets` scenario cannot pass, so it is not split. Stages 2 and 3 are independent and merge in either order; stage 4 comes last, because its check fails until they are done.

## Acceptance criteria

- [ ] No two scenarios resolve to the same helper container name, network, host directory or published port, shown by the check in stage 4.
- [ ] `uv run ./scripts/molecule-test-all.sh -j 4` passes for every role that starts a helper, in a cloud session and in CI's Molecule job.
- [ ] The two `not_running` scenarios still assert an absent container, and pass beside the scenarios that start the helper.
- [ ] [`molecule-testing.md`](../topics/testing/molecule-testing.md) no longer lists scenarios that cannot run side by side.
- [ ] `pre-commit run --all-files` passes.

## Agent handoff

Stop conditions are in [`README.md#stop-conditions`](README.md#stop-conditions); they apply without being restated here.

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced. It is not set yet: the change that starts stage 1 sets it, derived with [`suggest_project_scope`](../topics/documentation/project-checks.md#scope-suggestions) and not from this list. A starting point: `ansible/roles/molecule_helpers/**`; `ansible/roles/<role>/molecule/**` for each role in the inventory above; the new test under `ansible/tests/`; [`molecule-testing.md`](../topics/testing/molecule-testing.md) and [`molecule-fixtures.md`](../topics/testing/molecule-fixtures.md). Sweep terms: `step-ca-test`, `openbao-test`, `lldap-test`, `seaweedfs-test`, `molecule-openbao-test`, `lldap-test-certs`.
- **Must not change:** the scenario platforms' `molecule.yml`; production compose files and roles under test; the images and digests.
- **Relevant files and interfaces:** `ansible/roles/molecule_helpers/tasks/start_{step_ca,openbao,lldap,seaweedfs}_test_target.yaml`, each with its own header comment listing its variables; [`molecule-fixtures.md`](../topics/testing/molecule-fixtures.md) for the helper files; `ansible/scripts/molecule-test-all.sh` for what `-j` runs and prints; `reset_coverage_data.yaml`, which already reads `MOLECULE_SCENARIO_NAME` from the environment.
- **Required checks:** `pre-commit run --all-files`, with the hooks that need Docker or network skipped and named; the scenarios of every role a change touches. To reproduce the collision, and later to show it gone, from the repository root in a cloud session ([`hosted-sessions.md`](../topics/engineering/hosted-sessions.md#running-molecule) has the setup):

```bash
(cd ansible && uv run ./scripts/molecule-test-all.sh -j 4 secrets)
```

Run it as a tracked background command with the longest timeout, since a serial run of the ten scenarios takes much longer than a foreground command is given. The hook that prepares a session restarts `dockerd` when the session resumes, and that ends a run in progress.

## Risks

- [`molecule-container-hardening.md`](molecule-container-hardening.md) edits the same `start_*_test_target.yaml` files and many of the same scenarios, so whichever lands second rebases onto the first. The two do not depend on each other.
- A scenario that checks a name by value (a certificate SAN, an `api_addr`, a DNS name in a verify task) breaks if the helper renames the container and the check keeps the literal. Each stage's scenarios are run for real, not read.
- A published host port is a fixed number a scenario picks. A new scenario that picks one already taken fails only when run beside the other, which is what the stage 4 check is for.

## Open items

1. How a scenario gets its names. The helper could derive a default from `MOLECULE_SCENARIO_NAME` and the role, and expose the result as a variable for converge, verify and cleanup to read, so a new scenario cannot forget; or each scenario could pass a name of its own. The first needs the scenario name to be reachable in a `cleanup` playbook, which runs without the facts of the play that started the helper, so stage 1 checks that before choosing.
2. What the stage 4 check can decide. A name built from `MOLECULE_SCENARIO_NAME` is unique by construction and a literal is not, so the check may only need to fail on a literal helper name in a scenario. It is settled when the check is written.
3. Whether the roles that share `caddy-proxy` need a network each, or can share one the first creates and the last removes. Stage 2 settles it by running them side by side.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy. In the closing change, also drop the link to this project from the open exploration of Molecule core use, or delete that exploration if its question has ended.
