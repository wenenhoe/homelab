---
id: PROJ-credential-expiry-rename
title: "Rename the Credential Freshness Check to Credential Expiry"
type: project
status: not-started
blocked: false
summary: Give the cloud-credential expiry check its own name, so "freshness" means only the backup check.
allowed_paths:
  - tools/cloud_credentials/**
  - tools/tests/cloud_credentials/**
  - ansible/inventory/group_vars/cd_agent.yaml
  - ansible/roles/cd_agent/molecule/**
  - docker/openbao/policies/cd-agent-freshness.hcl
  - docker/openbao/policies/cd-agent-credential-expiry.hcl
  - docker/openbao/policies/rotation-read-watcher.hcl
  - docker/openbao/watcher/rotation_read_watcher.py
  - docs/topics/deploy/cd-agent-host.md
  - docs/topics/secrets/cloud-credentials/creation.md
  - docs/topics/secrets/cloud-credentials/expiry.md
  - docs/topics/secrets/openbao-cd-agent-approles.md
  - docs/topics/secrets/openbao-reinit-runbook.md
  - docs/topics/secrets/openbao-rotation-read-watcher.md
  - docs/architecture/secrets-and-credentials-flow.md
  - docs/projects/cd-agent.md
  - docs/projects/cd-agent-approles.md
  - docs/projects/cd-agent-controller-approle-retirement.md
  - docs/projects/credential-expiry-rename.md
  - docs/decisions/0020-*/revision-001.md
  - docs/decisions/0023-*/revision-000.md
  - docs/decisions/0025-*/revision-000.md
  - docs/decisions/0026-*/revision-000.md
  - docs/decisions/0041-*/revision-000.md
  - docs/decisions/0045-*/revision-000.md
  - docs/decisions/0104-*/revision-000.md
  - docs/decisions/0109-*/revision-000.md
  - docs/decisions/0110-*/revision-000.md
---

# Rename the Credential Freshness Check to Credential Expiry

Two unrelated checks are both called "freshness". One warns before a cloud
credential expires (`cloud_credentials.check_freshness`, the `controller` user
timer and the CD agent's `freshness` job). The other confirms each app's S3
backup is recent (`check-freshness.sh` and its hourly timer on every backup
host). Both ship a unit called `check-freshness`. The credential check is renamed
`credential-expiry` wherever its name will live on; the backup check keeps its name,
which its variables and units (`backup_freshness_*`, `telegram-notify-backup-freshness`)
already qualify. The weekly user timer on `controller` is not renamed: the CD agent's
job replaces it and [`cd-agent-controller-approle-retirement.md`](cd-agent-controller-approle-retirement.md)
removes it, so new unit names would be work thrown away. Its units keep their names and
run the renamed module until then. It is a project and not one pull request because the
live pieces (that timer's command, the CD agent's job, AppRole and heartbeat) are changed
by hand after the code changes. The project does not wait for the CD agent to go live:
renamed before the AppRoles exist, the new names are simply what get created.

## Scope

What is renamed, from the credential check only:

- the module `cloud_credentials.check_freshness` and its test, to
  `cloud_credentials.check_credential_expiry`;
- the command in the `controller` unit `check-freshness.service`, which names the
  module; the units themselves keep their names;
- the CD agent job `freshness`, to `credential-expiry`: its unit, user, credential
  and state directories, its AppRole `cd-agent-freshness` and that role's policy file,
  and its heartbeat id, endpoint and token (`cd-agent-freshness`,
  `gatus-token-cd-agent-freshness`);
- the docs, molecule scenarios and project docs that name any of these.

Not in scope: new names for the `controller` units, which the retirement project
removes; the backup freshness check and its units, variables and docs
(`check-freshness.sh.j2`, `check_freshness.bats` and the shell-tests doc that
describes it); what
the credential check does, its exit codes and its warning ladder; the rules of the
AppRole's policy; and the rotation read-watcher, apart from the role name its doc
gives.

## Decision

None needed: a name is not a choice that would surprise a reader of the code. The
AppRole is defined by [ADR 0020 revision 1 (Automation identity scope)](../decisions/0020-automation-identity-and-access-scope/revision-001.md),
`approved`, so the stage 1 change edits the name there in place, as that status
allows. The other decision revisions that name the module keep the old name with the
moved-file note
[`docs/decisions/README.md#editing-a-revision`](../decisions/README.md#editing-a-revision)
describes.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Rename in the repository | Not started | no tracked file outside decision history names `check_freshness` or `cd-agent-freshness`; the `controller` unit's command names the renamed module; the credential check's tests and the CD agent role's molecule scenario pass under the new names; the CD agent, AppRole, watcher and expiry docs use them |
| 2 | Move the live pieces | Not started | `controller`'s `check-freshness.service` runs the renamed module and its last run succeeded; any `cd-agent-freshness` AppRole already in OpenBao has a `cd-agent-credential-expiry` successor with the same policy rules, and a CD agent host that already runs the job runs it under the new name |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 2 — Move the live pieces

By hand, as the watcher's move was done. On `controller`, install the service unit again
the way [`expiry.md`](../topics/secrets/cloud-credentials/expiry.md#scheduling)
describes, so its command names the renamed module, reload, and run the service once.
If the `cd-agent-freshness` AppRole exists, create the new one from the renamed policy and
deliver its credentials to the CD agent host before removing the old files. With no such
role and no job on the host yet, this part has nothing to move. Deleting
the old role and its policy takes a root session, which `vault-bootstrap` and
`controller` do not have, so they are left in place and recorded the way the
watcher doc records its own.

## Acceptance criteria

- [ ] The credential check has one name in its module, job, AppRole, heartbeat and docs, and "freshness" names only the backup check and the `controller` units until they are removed.
- [ ] The weekly credential check on `controller` runs the renamed module and still raises the same three watcher alerts, all naming one role.
- [ ] The renamed CD agent job passes its molecule scenario, including its heartbeat and credential-file checks.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced. Stage 2 is run by the operator, not by a pull request.
- **Must not change:** the backup freshness check, the credential check's behaviour or exit codes, or the rules of any AppRole policy.
- **Relevant files and interfaces:** `tools/cloud_credentials/check_freshness.py`, `ansible/inventory/group_vars/cd_agent.yaml`, `docker/openbao/policies/cd-agent-freshness.hcl`, and the `cd_agent` role's molecule scenario.
- **Required checks:** `pre-commit run --all-files`, `uv run pytest ansible/tests tools/tests`, and the `cd_agent` molecule scenario in CI.

## Risks

- [`cd-agent.md`](cd-agent.md) and [`cd-agent-approles.md`](cd-agent-approles.md) are `building` and name the old job and role. Renaming before the AppRoles are live is cheap; after, stage 2 replaces a live role. Their docs change in prose only, and a project that closes first drops out of this one's scope.
- A job's user is `cd-agent-` plus its name. `cd-agent-credential-expiry` is 26 characters, under the 32 a Linux user name allows.
- The heartbeat for the CD agent job is not registered yet, so the renamed endpoint starts with no history to lose.

## Open items

None.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
