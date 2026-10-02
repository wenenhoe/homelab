---
id: PROJ-unit-test-quality-passes
title: "Unit Test Quality Passes"
type: project
status: building
blocked: false
summary: "Bring the converted Python unit tests in line with ADR 0070's rules for doubles and the conventions' assertion rules, one pass per change."
decision: ADR-0070/0
allowed_paths:
  - ansible/tests/**
  - tools/tests/**
  - docs/topics/engineering/conventions.md
---

# Unit Test Quality Passes

Brings the pytest-native suite in `ansible/tests/` and `tools/tests/` into line with what a test double is bound to and what a test asserts. Staged because each pass changes what tests check, so each is reviewed case by case in its own change; a bulk edit would hide the real mismatches a pass exists to surface.

## Scope

The test files and test-support modules under `ansible/tests/` and `tools/tests/`, and the Python unit tests section of `docs/topics/engineering/conventions.md`. Not in scope: the code under test, which a pass changes only if it finds a call the real interface rejects (see Agent handoff); which behaviors get a test; Molecule scenarios; mutation testing as a standing tool.

## Decision

Implements [ADR 0070](../decisions/0070-what-a-unit-tests-doubles-are-bound-to/revision-000.md), `approved`. The assertion and input rules are not an ADR; they are written in the Python unit tests section of [`conventions.md`](../topics/engineering/conventions.md), and stages 1 and 5 bring existing tests into line with them.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Tests with no assertion, or only mock-call assertions | Done | Every test meets the Assertions rule: it asserts an outcome the code decides, and a mock-call check includes the arguments. A test that cannot be given one is deleted, with the reason in its commit message. |
| 2 | Same-file families of tests whose bodies differ only in constants | Done | Each family is one `parametrize` test with ids, or the commit message names why its cases are not one behavior. |
| 3 | Real stand-ins for responses, processes, sessions, SDK objects and clients | Done | No bare `Mock` or `MagicMock` stands in for a response, process, session, client, key or channel; the shared factories are listed in the conventions' Fixtures bullet, and the conventions state ADR 0070's rule for new tests. |
| 4 | `autospec` on every remaining replaced function and method | Done | Every `patch` that does not pass `new=` or `new_callable` has `autospec=True`; no `patch.object` reaches a builtin through a module; every function a test replaces with a double that records its calls or returns a canned value, whether by `patch` or by `monkeypatch.setattr`, is a `create_autospec` of the real one. A fake with behaviour of its own (`FakeVault`) and a plain value (a path, an argv list) are not doubles. |
| 5 | Pass-through values and impossible inputs | Not started | No test stubs a collaborator to return a constant and asserts the code returns that constant when the code could hard-code it; every `None` or wrong-typed argument names the outside source that can produce it, or is removed. |

Stage 3 comes before stage 4: forcing `autospec` onto every eligible `patch` as a one-off run failed 18 tests that read attributes an autospec'd class does not have (`requests.Session.headers`, the `session` of a b2sdk `B2Api`), and a real object is the answer to each. Stage 3 may be split by collaborator (requests, subprocess, b2sdk, hvac, paramiko, OCI) across several changes; each stays a change of its own.

## Acceptance criteria

- [ ] Every stage's exit condition is met.
- [ ] `uv run pytest ansible/tests/ tools/tests/` passes, and `ruff check` and `ruff format --check` are clean on both test directories.
- [ ] For every change that edited what a test asserts or doubles, no mutant of the code under test that a test failed on before the change passes after it.
- [ ] The conventions describe every rule the passes applied, and ADR 0070 is `accepted`.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** the code under test. A flip that shows the real interface rejecting a call stops the pass: the fix is in the code under test, which is outside `allowed_paths`, so widening the scope is its own reviewed change first. ADR 0070 beyond the edits [`docs/decisions/README.md#assumptions`](../decisions/README.md#assumptions) permits an agent.
- **Relevant files and interfaces:** the `[tool.pytest]` table in `pyproject.toml`; the shared fixtures in `tools/tests/conftest.py`, `tools/tests/cloud_credentials/conftest.py`, `tools/tests/doc_scripts/conftest.py` and `tools/tests/ci/conftest.py`; the Python unit tests section of the conventions.
- **Required checks:** the full suite and `ruff` as above, `pre-commit run --all-files`, and for a change that edits assertions or doubles, a mutation comparison: mutate the code under test one site at a time, run the old and new tests together, and require that no test which failed before passes after. The harness is a throwaway script kept outside this repo; run it and say so in the change.

## Risks

- `tools/tests/ci/test_layout.py` parametrizes over every Python file under `tools/tests/`, so adding or deleting a factory module or `conftest.py` changes the collected test count by one. Turning a `subtests` loop into `parametrize` turns one test plus N subtests into N tests. Each change states the count it expects.
- The `TestRealTree` tests in `tools/tests/ci/scope/test_molecule_scope.py` scan the real repo at about two seconds each, and the file takes about 26 seconds of the suite's run. A pass must not multiply them, for instance by parametrizing one over more cases.
- A shared factory tracks an SDK's constructor. A locked-version bump that changes one fails the factory's tests loudly, in one place.

## Open items

- `tools/cloud_credentials/rotation_keys/oci_iam.py` has no test file. Whether it gets one is a question about which behaviors are tested, which ADR 0070 leaves out; settle it separately from this project.
- Whether `mutmut` adds signal on the pure-logic modules is an open spike, separate from these passes and from ADR 0070.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] Every bullet of the linked revision's Decision is implemented, or named by a successor project.
- [ ] The linked revision is `accepted`, another project still names it, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
