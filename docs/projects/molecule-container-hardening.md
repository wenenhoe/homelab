---
id: PROJ-molecule-container-hardening
title: "Molecule Container Hardening"
type: project
status: not-started
blocked: false
summary: "Give every helper container and compose fixture a Molecule scenario starts the same cap_drop and no-new-privileges defaults as a service, with only the capabilities its process needs, and add a check that a new one cannot omit them."
allowed_paths:
  - ansible/roles/molecule_helpers/**
  - ansible/roles/*/molecule/**
  - ansible/tests/test_molecule_container_hardening.py
  - docs/topics/engineering/molecule-testing.md
  - docs/topics/engineering/molecule-fixtures.md
  - docs/topics/deploy/container-hardening.md
---

# Molecule Container Hardening

[`AGENTS.md`](../../AGENTS.md) and [`container-hardening.md`](../topics/deploy/container-hardening.md) say every service and every helper container sets `cap_drop: [ALL]` and `no-new-privileges:true`, then adds back only what its process does. The containers a Molecule scenario starts besides its own platform (the target services in `molecule_helpers`, the throwaway containers in `converge.yml` and `verify.yml`, and the generic compose fixtures) set neither. It is staged because each container's capability set has to be found and shown to work on its own image, and the ones that are not one image are many files in many roles.

## Scope

In: the four target services `molecule_helpers` starts (OpenBao, lldap, SeaweedFS, step-ca) and the step-cli and chmod containers beside the OpenBao one; the host paths the chmod container mounts and the modes of the directories it works in; the compose files under `ansible/roles/molecule_helpers/fixtures/` and the scenario fixtures that are not symlinks to a production file; the one-off `community.docker.docker_container` tasks in the scenarios' `converge.yml`, `verify.yml` and `prepare.yml`; a test that fails for a container in these places that sets neither default; the Molecule and container-hardening topic docs.

Not in: the scenario platforms (`privileged: true` systemd containers), which [`coding-agent-molecule-runtime.md`](coding-agent-molecule-runtime.md) decides; fixtures that are symlinks to a production compose file, which inherit its settings; production compose files and the playbooks under `ansible/playbooks/`, which already set both defaults; the images' versions and digests.

## Decision

None gates this: the rule is the standing default in `AGENTS.md`, not a choice between options. If a helper turns out to need a capability the production service of the same image does not, that is a finding about the image, and the work stops there ([`README.md#stop-conditions`](README.md#stop-conditions)).

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | The target services and helpers in `molecule_helpers` | Not started | Each sets `cap_drop: [ALL]`, `no-new-privileges:true` and the capabilities its image needs, taken from the production compose file of the same image where one exists. The chmod container mounts only the files it changes. Every scenario that uses a target passes in CI, and a target is started, stopped and started again once with the set on, on a fresh volume and on a populated one |
| 2 | The generic compose fixtures | Not started | Each fixture that is not a symlink sets both defaults, and the scenario that deploys it passes, including its idempotence step |
| 3 | The one-off containers in scenario playbooks | Not started | Each `docker_container` task in a `converge.yml`, `verify.yml` or `prepare.yml` sets both defaults, and its scenario passes |
| 4 | The check and the docs | Not started | A test fails for a container in these places that sets neither default, and fails when a task that sets them is changed to drop them. The Molecule and container-hardening docs say the defaults apply to what a scenario starts |

Stage status is `Not started`, `In progress`, or `Done`. Stages 1 to 3 are independent and can merge in any order; stage 4 comes last, because it fails until they are done.

## Acceptance criteria

- [ ] No `community.docker.docker_container` task and no non-symlink compose file under the paths in Scope starts a container without `cap_drop: [ALL]` and `no-new-privileges:true`, shown by the check in stage 4.
- [ ] Each capability a helper keeps is one its process needs, shown by the same container failing without it.
- [ ] Every Molecule scenario that starts one of these containers passes in CI, including its restart where it has one.
- [ ] `pre-commit run --all-files` passes.

## Agent handoff

Stop conditions are in [`README.md#stop-conditions`](README.md#stop-conditions); they apply without being restated here.

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** the scenario platforms' `molecule.yml`; the production compose files the fixtures link to; the linked rule's text in `AGENTS.md`.
- **Relevant files and interfaces:** [`container-hardening.md`](../topics/deploy/container-hardening.md) for choosing and verifying a set; the production compose file of each image (`docker/openbao/`, `docker/lldap/`, `docker/seaweedfs/`, `docker/step-ca/`); `ansible/roles/molecule_helpers/tasks/start_*_test_target.yaml`; [`molecule-fixtures.md`](../topics/engineering/molecule-fixtures.md).
- **Required checks:** `pre-commit run --all-files` with the hooks that need Docker or network skipped and named; `uv run pytest` from `tools/` and `ansible/tests`; the scenarios of every role a change touches, which run in CI.

## Risks

- The pinned images cannot be pulled in an agent's sandbox, so a capability set is derived from the production service of the same image and shown by the scenario's run in CI, not by running the image beforehand. A set that is too small shows as a failing scenario, not as a quiet success: `CHOWN`, `FOWNER` and `FSETID` can fail without a non-zero exit ([`container-hardening.md`](../topics/deploy/container-hardening.md)), so each scenario that depends on file ownership or mode checks the result and not only the exit code.
- A fixture that mirrors a production service is derived from its production file, not authored again from memory.

## Open items

1. Whether the host's `/tmp` bind mount and the `0777` directories in the OpenBao helper exist for a reason the chmod container's narrower mount would break, such as a file the next container reads as another user. Stage 1 settles it by running the scenarios, and the answer goes in the topic doc.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
