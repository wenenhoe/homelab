---
id: PROJ-watch-all-rotation-credentials
title: "Watch All Rotation Credentials"
type: project
status: building
blocked: false
summary: Make the OpenBao read-watcher alert on a read of the B2 and OCI rotation secrets as well as R2's, as ADR 0026 revision 1 decides.
decision: ADR-0026/1
allowed_paths:
  - docker/openbao/watcher/**
  - docker/openbao/policies/r2-read-watcher.hcl
  - docker/openbao/policies/rotation-read-watcher.hcl
  - docker/openbao/policies/cd-agent-freshness.hcl
  - ansible/tests/test_r2_read_watcher.py
  - ansible/tests/test_rotation_read_watcher.py
  - ansible/inventory/group_vars/all/main.yaml
  - ansible/inventory/group_vars/all/secret_catalog.yaml
  - .github/detect-changes-filters.yml
  - tools/openbao_utils/client.py
  - tools/rebuild_check/host.py
  - tools/tests/rebuild_check/test_host.py
  - tools/tests/ci/promotion/test_rules.py
  - docs/topics/secrets/openbao-r2-read-watcher.md
  - docs/topics/secrets/openbao-rotation-read-watcher.md
  - docs/topics/secrets/openbao-reinit-runbook.md
  - docs/topics/secrets/cloud-credentials/scoping.md
  - docs/topics/monitoring/gatus.md
  - docs/topics/README.md
  - docs/topics/disaster-recovery/rebuild-runbook.md
  - docs/topics/disaster-recovery/rebuild-tools.md
  - docs/topics/engineering/ci/change-scoping.md
  - docs/topics/engineering/ci/pipeline.md
  - docs/topics/engineering/nist-800-53-alignment.md
  - docs/architecture/secrets-and-credentials-flow.md
  - docs/decisions/0045-*/revision-000.md
  - docs/decisions/0105-*/revision-000.md
  - docs/projects/watch-all-rotation-credentials.md
---

# Watch All Rotation Credentials

The watcher alerts on a read of one Vault path, the R2 rotation token's. The
other two rotation credentials, B2's application key and OCI's client secret,
are audited but raise nothing. Three stages: the watching, then a rename
because the name no longer fits, then a hand install on `security`, where
the code and its docs change in the repository and the result has to be
installed by hand.

## Scope

The watcher script's one-path constant becomes a fixed set of the three
secret-bearing paths, its alert names the path that was read, its tests cover
each member and the identifier-only paths that stay unwatched, and the topic
docs describe the set and the expected weekly alerts. The watcher then takes
a name that fits all three paths, `rotation-read-watcher`, in place of
`r2-read-watcher`: the script, its units and timer, the state and credential
directories, the AppRole and its policy, and the heartbeat job with its token.
Not in scope: the audit device, the policy's rules, and the heartbeat's
cadence, which do not change.

## Decision

Implements [ADR 0026 revision 1 (High-value secret read alerts)](../decisions/0026-detecting-reads-of-high-value-secrets/revision-001.md).
Rationale and the watched set are there.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Watch the three paths, in code, tests and docs | Done | `test_r2_read_watcher.py` shows an alert for a read of each of the three paths that names it, none for an identifier-only path, and one alert per read; the watcher doc's expected-alerts section and `scoping.md` describe the watched set |
| 2 | Rename to `rotation-read-watcher` | Not started | no tracked file outside decision history and the fire-drill record names `r2-read-watcher` or `r2_read_watcher`; the watcher's tests and `rebuild_check` use the new names; the watcher doc, the Gatus doc and ADR 0026 revision 1 describe the new name |
| 3 | Install on `security` | Not started | the renamed watcher runs on `security` under its new AppRole and heartbeat, the old units and directories are gone from it, and the next weekly freshness run raised three alerts naming the role that ran it and no other |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 3 — Install on `security`

The script is installed by hand ([the watcher doc](../topics/secrets/openbao-r2-read-watcher.md)).
The old install is replaced, not renamed in place: the new AppRole, its
`secret_id`, the heartbeat token and the new units are created first, the state
file is carried over so the new unit resumes without re-alerting on past reads,
and only then are the old units and directories removed. The resume record's
format is unchanged, so an old record stays valid.

## Acceptance criteria

- [ ] A read of any of the three rotation secrets raises an alert that names which one.
- [ ] A read of an identifier-only path raises none.
- [ ] The weekly freshness run raises exactly three alerts, all naming the same role.
- [ ] The watcher doc and `scoping.md` describe the watched set, not one path.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced. Stage 3 is run by the operator on `security`, not by a pull request.
- **Must not change:** the rules of the watcher's AppRole policy, the audit device, or the resume record's format.
- **Relevant files and interfaces:** [`r2_read_watcher.py`](../../docker/openbao/watcher/r2_read_watcher.py) and its test, `ansible/tests/test_r2_read_watcher.py`.
- **Required checks:** `pre-commit run --all-files`, and the watcher's tests.

## Risks

- A mistyped path in the set alerts on nothing, so the test names each of the three paths literally.
- Three alerts a week instead of one may read as noise at first; the doc says what the trio is.

## Open items

- The old `r2-read-watcher` AppRole, its policy and the `gatus-token-r2-read-watcher`
  secret stay in OpenBao after stage 3: neither `vault-bootstrap` nor `controller`
  can delete them, only a root session can. Nothing holds the old `secret_id` once
  stage 3 has removed its file. Remove all three the next time a root session is
  open, or accept them and say so here before the project closes.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
