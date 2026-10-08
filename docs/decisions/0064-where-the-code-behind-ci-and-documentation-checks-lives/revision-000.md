---
id: ADR-0064
revision: 0
type: adr
title: "Where the code behind CI and documentation checks lives"
short: CI and doc check code
solution: "Code that decides a check's outcome is unit-tested Python under tools/, one package per domain; .github/ keeps only what Actions reads and plain command sequences"
summary: "Where the logic that decides what CI runs, whether a gate passes, and whether the docs are consistent lives, so it can be tested and isn't copied between workflows."
topic: repository-tooling
status: accepted
related: [ADR-0031, ADR-0037]
---

# 0064. Where the code behind CI and documentation checks lives

## Problem

CI and pre-commit run code that decides things: which jobs a change needs,
whether a gate passes, whether a docs invariant holds, what an image is
tagged. That code has to be testable without running the workflow, runnable
locally exactly as CI runs it, defined once, and found in one predictable
place, not buried in workflow YAML.

## Context

[ADR 0031](../0031-where-repo-tooling-lives/revision-000.md) put
controller-side utilities under `tools/`, split by domain. It doesn't cover
CI or the documentation checks, and those had grown up in three places:

- inline `run:` blocks in workflows, with no way to test them;
- bash and Python side by side in `.github/scripts/`;
- the documentation-workflow scripts from
  [ADR 0037](../0037-decision-and-project-documentation-workflow/revision-002.md),
  also in `.github/scripts/`, while their tests live in
  `tools/tests/doc_scripts/` and reach back across with a `sys.path` edit.

The cost showed in specifics. The compose exclusion list was parsed three
times, once per consumer. An image's tag was worked out by three different
mechanisms, two of them a bare `grep` that never checked it had matched
exactly one line, and nothing checked that a compose file's pin equalled
the tag the build would publish. The rule that decides whether a merge is
blocked (`matrix-jobs-gate`) and the rule that classifies the deploy-ordering
check's log were shell with no tests. Code in `.github/scripts/` also can't
be imported by a test as a package, so the `python_unit_tests` trigger had to
list individual files.

Three facts constrain the design, each checked in the repo rather than
assumed:

- pre-commit's local hooks run a script in an isolated environment holding
  only the dependencies the hook declares (`additional_dependencies`), and
  the documentation scripts import only the standard library and PyYAML;
- several jobs install nothing (the small aggregator and setup jobs), and the
  image-build jobs hold a package-write token, so a dependency installed in
  them widens what a compromised package could reach;
- `tools/` shares one `sys.path` convention (a package under `tools/`, run
  from there as `python -m`), and a package named like a standard-library
  module shadows it, as [ADR 0031](../0031-where-repo-tooling-lives/revision-000.md)
  found for `secrets`.

## Decision

Code with a pass/fail rule or a decision in it is Python under `tools/`, in
a package named for its domain, and nothing else in the repo decides it.

- `tools/ci/` holds what workflows run, in submodules by domain: `scope`
  (what a diff needs tested), `gates` (checks with their own verdicts),
  `images` (image names, tags and CI builds), `scan` (setup for security
  scans) and `fixtures` (data CI seeds into a job).
- `tools/doc_scripts/` holds the documentation-workflow checks and
  generators of ADR 0037. They move from `.github/scripts/`: the
  hyphenated script names become importable modules, and the shared
  helpers they import as top-level modules become package imports.
- `tools/ci/fixtures/` holds the two deploy-ordering fixture helpers,
  `preseed-manual-secrets-for-ci.py` and `strip-vault-scope-for-ci.py`,
  which have no tests today. They move as `preseed_manual_secrets.py` and
  `strip_vault_scope.py`: the package name already says they are for CI, so
  the `-for-ci` suffix goes, and underscores make them importable. They gain
  tests when they move.
- Tests live in `tools/tests/`, mirroring the package layout. A change under
  a package triggers the Python unit tests, and no test imports code from
  `.github/`.
- Workflows and pre-commit call these as `python -m <package>.<module>` from
  `tools/`. They pass inputs (revisions, file lists, `toJSON(needs)`) and
  carry no rule of their own.
- `.github/` keeps what GitHub or Actions reads, and shell that only
  sequences commands: workflow and composite-action YAML, the path-filter
  and exclusion data files, the Renovate config, image smoke tests, and
  scripts that only orchestrate `docker` or `ansible-playbook`
  (`seed-lldap-ci-cert.sh`). The test for staying is whether a unit test
  would check something other than a mock.
- A module a job runs on the runner's own `python3` imports only the
  standard library and its own package, and parses on an older Python than
  the repo's. Other modules run through `uv run`, or through pre-commit's
  declared dependencies.

The move changes no check's rules. Where a module replaces shell, the two
are compared on real inputs and any deliberate difference is stated in the
change that makes it.

## Alternatives considered

- **Keep the documentation scripts in `.github/scripts/` and put only new CI
  code in `tools/`.** Two homes for the same kind of code, and the tests
  keep reaching across with `sys.path`. It was the cheapest option and
  loses on every constraint above except effort.
- **Move the shell that only sequences commands into `tools/` as well.** A
  unit test of `seed-lldap-ci-cert.sh` in Python would mock `docker`, so it
  proves nothing the workflow run doesn't, and `.github/` is where Actions
  reads its inputs from.
- **Leave the logic inline in the workflows.** Untestable, and already
  duplicated three times.
- **A second top-level directory for CI code.** Repeats the scatter that
  ADR 0031 fixed; `tools/` is already the place.

## Consequences

- A CI job that ran a shell one-liner now starts Python, and one that
  needed no checkout (the merge gate) now checks out `tools/ci`. That is
  seconds per job, accepted for tests.
- The documentation hooks run as
  `bash -c 'cd tools && python3 -m doc_scripts.<module>'`, the way the
  image-pin hook already does.
- Every place that names a moved path changes with it: links in
  `docs/README.md`, `AGENTS.md`, `README.md`, `docs/topics/engineering/ci/pipeline.md` and
  `docs/topics/engineering/molecule-fixtures.md`, the `allowed_paths` example in
  `docs/projects/README.md`, and any project's own `allowed_paths`.
- A change to a check is reviewed with the code it checks, and the code that
  runs is the PR's own. That is already true of every workflow and is
  unchanged here.
- The resulting layout is described in
  [`docs/topics/engineering/ci/pipeline.md#where-the-ci-logic-lives`](../../topics/engineering/ci/pipeline.md#where-the-ci-logic-lives).

## Invariants

- Each verdict a workflow or hook acts on is computed in one place, and a
  test exercises it.
- A workflow step's `run:` is a command line, not a rule.
- A module documented as standard-library-only stays so.
- Package names don't shadow the standard library.

## Non-goals

- The Ansible-side controller scripts that
  [ADR 0031](../0031-where-repo-tooling-lives/revision-000.md) and its
  successors placed. Those decisions stand.
- Converting shell that only sequences commands.
- Changing what any check enforces. The documentation scripts' rules are
  ADR 0037's.

## Validation

`tools/tests/ci/test_stdlib_only.py` enforces the standard-library-only rule
and that the workflows call those modules with plain `python3`.
`tools/tests/ci/test_layout.py` asserts `.github/scripts/` holds no Python,
that no test or caller runs code from it, that every module a workflow or hook
runs exists, and that every package under `tools/` triggers the Python unit
tests by directory.

## Reconsideration triggers

- CI moves off GitHub Actions, as
  [ADR 0044](../0044-prod-automation-trigger-and-execution/revision-000-b.md)'s
  Gitea-or-Forgejo candidate would. `.github/` would change and `tools/`
  would not, which is the point of the split, but the invocation lines
  would need review.
- A CI module needs a third-party dependency in a job that holds a write
  token.
- A runner's `python3` falls behind what the standard-library-only modules
  need.
