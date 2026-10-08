# Mutation testing

Mutation testing is run by hand, occasionally, with tooling that lives in the private security repo, not here. It is not part of CI and has no schedule. A result depends only on the code, the tests and the tool's version, so it changes only when one of them does, and a run is worth making when you have just changed them.

[ADR 0069 (Python test style)](../../decisions/0069-how-python-unit-tests-are-written-and-run/revision-000.md) and [ADR 0070 (Test doubles binding)](../../decisions/0070-what-a-unit-tests-doubles-are-bound-to/revision-000.md) left it out until a spike showed whether it adds signal. On the credential tooling it did: it found behaviours that review and the suite had both passed, and each became an ordinary test change. That is the use it is kept for.

## When to run it

- You add or rewrite the tests of a module that handles credentials (`tools/cloud_credentials/`).
- You add tests for a new module under `tools/`.
- A change rewrites tests without changing the code under test: a conversion, a rebinding of doubles, a pass that strengthens assertions. The tooling can compare which individual tests fail before and after, which shows whether any test lost a kill. A project that makes such a change names that comparison in its required checks.

## Reading a survivor

A survivor is a change the tests did not notice. It is a prompt to look, not a defect.

- A change to message or label text alone is usually not worth a test.
- A boundary that differs only at the exact instant a clock is read cannot be tested without a clock seam the code does not have, and is left.
- A mutant in a function no test reaches means that function has no test.
- Anything else is a behaviour a test should assert: an argument passed, a timeout set, an exit code, a comparison's edge.

## Keeping results private

A run's output is a list of the behaviours no test guards. That is what [`docs/README.md#public-repo`](../../README.md#public-repo) keeps out of git history, and a public repository's Actions logs are public too. So it runs on your machine or in an agent session, never in CI, and its output goes nowhere public: not a commit message, a pull request, an issue or a doc.

A survivor is closed by an ordinary test change, described by the behaviour it asserts. The commit message does not say a mutant, a survivor or a mutation tool prompted it.
