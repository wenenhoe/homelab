---
id: ADR-0069
revision: 0
type: adr
title: "How the repo's Python unit tests are written and run"
short: Python test style
solution: "pytest-native tests, with fixtures for setup and parametrize for variants; unittest-style tests are converted rather than left"
summary: "How Python unit tests are written and run so the suite has one style for setup, cases and assertions, and a failing case names its input."
topic: repository-tooling
status: accepted
related: [ADR-0064]
---

# 0069. How the repo's Python unit tests are written and run

## Problem

The Python unit tests need one style: one way to share setup, one way to write a table of cases, one way to assert, and one place that says where imports resolve from. A failing case has to name the input that failed, and converting or extending the suite must not depend on which style a file happens to use.

## Context

[ADR 0064](../0064-where-the-code-behind-ci-and-documentation-checks-lives/revision-000.md) requires the code that decides a check's outcome to be unit-tested, with tests in `tools/tests/` and `ansible/tests/`. `pytest` is the only runner (`pr-checks.yml` runs `uv run pytest ansible/tests/ tools/tests/`, locked at 9.1.1), but the tests are written against `unittest`. Measured on `main` when this was written:

- 229 test-file class definitions, about 1,560 `self.assert*` calls against about 170 bare `assert` statements, 86 `setUp`/`tearDown` and 80 `addCleanup` calls, and shared setup held in `TestCase` base classes.
- 103 `self.subTest` uses and 20 `parametrize` uses.
- 67 `sys.path.insert` calls across 57 test files, and 48 `unittest.main()` blocks.

Two facts constrain the migration, both run against the locked `pytest` rather than assumed:

- `unittest.TestCase` classes, plain `pytest` functions and plain classes using the built-in `subtests` fixture run in one session, and a failing `self.subTest` case is reported per case. Conversion can therefore go directory by directory with the suite green throughout.
- `@pytest.mark.parametrize` does not apply to `TestCase` methods. A variant table in a `TestCase` can only be a `subTest` loop, which gives no test id.

## Decision

Tests are pytest-native.

- **Style.** Plain functions or plain classes, plain `assert`, `pytest.raises(..., match=)`. Fixtures replace `TestCase` base classes, `setUp` and `addCleanup`; `monkeypatch` and `tmp_path` come before anything hand-rolled. No new `unittest.TestCase`, and existing ones are converted, not left.
- **Variants.** Cases of one behavior are one `@pytest.mark.parametrize` test with readable ids. The `subtests` fixture is for cases that must share setup a parametrized test would repeat.
- **Import roots.** Declared once in the `pytest` configuration in `pyproject.toml`. A `conftest.py` holds only what configuration can't express. Test files carry no `sys.path` edits.
- **Order.** Configuration and shared fixtures first, with no test changes. Then one mechanical conversion per directory. A conversion changes no behavior and drops no assertion: the same behaviors are collected, each test keeps its assertions, and any difference is stated in that change. Fixes to what tests assert or double come afterward, as separate changes on the converted files.

The conventions are written down in a testing section of `docs/topics/engineering/conventions.md`, added with the first conversion.

## Alternatives considered

- **Stay on `unittest`, adding `subTest`.** The smallest change. It keeps two assertion vocabularies and a base-class layer that fixtures do directly, and gives no ids. `pytest` is already the runner, so `TestCase` is not there for a runner's sake.
- **Convert a file only when it is next touched.** Cheapest per change, but it leaves both styles in the suite indefinitely, which fails the one-style requirement.
- **Convert everything in one change.** One review to read, but 1,500-odd assertions rewritten at once makes a silently dropped assertion unreviewable.
- **Add `pytest-mock`.** Its `mocker` fixture does nothing `monkeypatch` and `unittest.mock.patch` don't already do, and it adds a package to `uv.lock`.

## Consequences

- One-time churn: about ten conversion changes. The risk is a dropped or weakened assertion, which the per-test check in the order above exists to catch.
- `python -m unittest` and running a test file as a script stop being supported. The tests already document `uv run pytest` as the way to run them.
- The layout and standard-library-only checks from ADR 0064 apply unchanged: they constrain the code under test, not the test framework.

## Invariants

- Once the migration closes, the suite holds one test style and no `sys.path` edits in test files.
- The import roots for tests are declared in one place.
- A conversion never lowers the number of assertions a test makes.

## Non-goals

- Rules for test doubles and assertion strength: what a mock is bound to, which values a pass-through test may use, which tests are deleted. That is a separate problem that would still stand if the framework changed, so it gets its own lineage before that work starts.
- Mutation testing. Whether it adds signal on the pure-logic modules is answered by a spike before any decision.
- Molecule scenarios and role testing, which [`docs/topics/engineering/molecule-testing.md`](../../topics/engineering/molecule-testing.md) covers.
- Which behaviors get a test.

## Reconsideration triggers

- `pytest` stops being the runner, or a plugin the suite depends on stops supporting the locked Python version.
- A group of tests can't be converted without losing coverage they have today.
