---
id: PROJ-watch-all-rotation-credentials
title: "Watch All Rotation Credentials"
type: project
status: not-started
blocked: false
summary: Make the OpenBao read-watcher alert on a read of the B2 and OCI rotation secrets as well as R2's, as ADR 0026 revision 1 decides.
decision: ADR-0026/1
allowed_paths:
  - docker/openbao/watcher/r2_read_watcher.py
  - ansible/tests/test_r2_read_watcher.py
  - docs/topics/secrets/openbao-r2-read-watcher.md
  - docs/topics/secrets/cloud-credentials/scoping.md
  - docs/decisions/0014-r2-rotation-credential-cannot-be-narrowed/revision-000.md
  - docs/projects/watch-all-rotation-credentials.md
---

# Watch All Rotation Credentials

The watcher alerts on a read of one Vault path, the R2 rotation token's. The
other two rotation credentials, B2's application key and OCI's client secret,
are audited but raise nothing. Two stages, because the code and its docs
change in the repository and the new script then has to be installed by hand
on `security`.

## Scope

The watcher script's one-path constant becomes a fixed set of the three
secret-bearing paths, its alert names the path that was read, its tests cover
each member and the identifier-only paths that stay unwatched, and the topic
docs describe the set and the expected weekly alerts. Not in scope: renaming
the script, unit or state directory, which touch a hand-installed host; the
audit device, the AppRole and the heartbeat, which do not change.

## Decision

Implements [ADR 0026 revision 1 (High-value secret read alerts)](../decisions/0026-detecting-reads-of-high-value-secrets/revision-001.md).
Rationale and the watched set are there.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Watch the three paths, in code, tests and docs | Not started | `test_r2_read_watcher.py` shows an alert for a read of each of the three paths that names it, none for an identifier-only path, and one alert per read; the watcher doc's expected-alerts section, `scoping.md` and ADR 0014's wording describe the watched set |
| 2 | Install on `security` | Not started | the updated script runs on `security`, and the next weekly freshness run raised three alerts naming the role that ran it and no other |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 2 — Install on `security`

The script is installed by hand ([the watcher doc](../topics/secrets/openbao-r2-read-watcher.md)):
copy it over, restart the unit, and check that the unit resumes from its
state file without re-alerting on past reads. The resume record is unchanged,
so an old record stays valid.

## Acceptance criteria

- [ ] A read of any of the three rotation secrets raises an alert that names which one.
- [ ] A read of an identifier-only path raises none.
- [ ] The weekly freshness run raises exactly three alerts, all naming the same role.
- [ ] The watcher doc and `scoping.md` describe the watched set, not one path.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced. Stage 2 is run by the operator on `security`, not by a pull request.
- **Must not change:** the watcher's AppRole policy, the audit device, or the resume record's format.
- **Relevant files and interfaces:** [`r2_read_watcher.py`](../../docker/openbao/watcher/r2_read_watcher.py) and its test, `ansible/tests/test_r2_read_watcher.py`.
- **Required checks:** `pre-commit run --all-files`, and the watcher's tests.

## Risks

- A mistyped path in the set alerts on nothing, so the test names each of the three paths literally.
- Three alerts a week instead of one may read as noise at first; the doc says what the trio is.

## Open items

None.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
