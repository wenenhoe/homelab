# CI: PR Checks

`.github/workflows/pr-checks.yml` runs on every PR. Which jobs actually
block a merge is configured in GitHub's branch protection / repository
rulesets (Settings > Branches on GitHub, not anything in this repo) —
see [Requiring checks before merge](#requiring-checks-before-merge)
below for which check names to select. This pipeline isn't a substitute
for [Molecule](molecule-testing.md): Molecule tests one role in
isolation, this pipeline tests the parts Molecule can't (linting the
whole tree, a real compose stack booting, and the actual
`deploy.yaml`/`restore.yaml` ordering).

## Change-scoped, not a full sweep

`detect-changes` diffs the PR's base/head and feeds most other jobs a
scoped input, so a docs-only PR doesn't trigger Molecule or boot-tests.
`pre-commit-checks` is the exception — it runs unconditionally on every
PR regardless of what changed, since its hooks span nearly every file
type in the repo:

- `roles` — any `ansible/roles/<role>/` touched maps to that role, except
  three repo-wide cases that map to *every* role instead, because
  nothing in them maps cleanly to a single consumer:
  `ansible/requirements.yml` (a Galaxy collection bump), any file under
  `ansible/roles/molecule_helpers/` (see
  [`#molecule_helpers-is-repo-wide`](#molecule_helpers-is-repo-wide)),
  and `pyproject.toml`/`uv.lock` (pins the `ansible-core` version every
  role's Molecule run actually executes under).
- `compose_apps` — any `docker/<app>/compose.yaml` touched, minus the
  exclusion list (below).
- `deploy_ordering` — `ansible/inventory/**`, `ansible/playbooks/**`,
  `ansible/roles/secrets/**`, `ansible/roles/restore/**`.
- `uv_lock` — `pyproject.toml`/`uv.lock` changed.

### `molecule_helpers` is repo-wide

`ansible/roles/molecule_helpers/` isn't a normal role — it has no
`molecule/` scenario of its own, so nothing under it is ever "the role
that changed." Every scenario's base config
(`.config/molecule/config.yml`, deep-merged into every DinD scenario)
resolves its Galaxy dependencies from `molecule_helpers/`'s
`role-requirements.yml`/`requirements.yml` unconditionally, and several
scenarios' `converge.yml` additionally `include_role` specific task
files from it directly (`bootstrap_docker.yaml`,
`start_seaweedfs_test_target.yaml`, etc.) — see each role's own
`converge.yml` for which. No single file in `molecule_helpers/` maps
cleanly to one consumer, so the `roles` filter treats any change under
it the same as a top-level `ansible/requirements.yml` bump: every role
with a `molecule/` scenario gets queued.

Concretely, this is what makes the `seaweedfs`
`compose-boot-test-exclusions.txt` entry below correct — see there for
the SeaweedFS-specific case this generalizes from.

## Jobs

| Job | Runs when | What it does |
| :--- | :--- | :--- |
| `pre-commit-checks` | always | Every commit-stage hook (all of `.config/.pre-commit-config.yaml` except `ansible-lint`) against every file. |
| `ansible-lint` | always | `ansible-lint`, the one push-stage hook — always lints the whole `ansible/` tree, not just what changed, so it's pinned to push time locally too (see `.config/.pre-commit-config.yaml`). |
| `uv-lock` | `pyproject.toml`/`uv.lock` changed | `uv sync --locked` — catches an unregenerated lockfile or a resolvable-but-broken dependency combination. |
| `deploy-ordering-check` | inventory/playbooks/secrets/restore/`pyproject.toml`/`uv.lock` changed | See below. |
| `molecule` | any role touched | One matrix job per changed role, running `./molecule-test-all.sh <role>`. Also generates and gates on that role's [coverage report](#molecule-coverage-gate). See [`molecule-testing.md`](molecule-testing.md). |
| `compose-boot-test` | any non-excluded compose file touched | Seeds and boots each changed app for real. See below. |
| `compose-syntax-check` | any compose file touched, fallback | `docker compose config --quiet` on whatever `compose-boot-test` excludes. |
| `matrix-jobs-gate` | always | Aggregates `molecule`/`compose-boot-test`'s results into one fixed check name — see below. |

## Requiring checks before merge

Not configured in this repo — GitHub only blocks merges via branch
protection rules or repository rulesets (Settings > Branches), which
reference jobs by their check-run name (`<workflow name> / <job name>`,
e.g. `PR checks / pre-commit-checks`).

`pre-commit-checks`, `ansible-lint`, `uv-lock`, `deploy-ordering-check`,
and `compose-syntax-check` are all safe to mark required directly: each
is gated by a job-level `if:` inside a workflow that always triggers on
`pull_request`, not by a path filter on the trigger itself — a required
check accepts a `skipped` conclusion, so an unrelated PR (e.g.
docs-only) won't get stuck waiting on a `deploy-ordering-check` run that
never needed to happen. The unsafe pattern (never used here) would be
`paths-ignore`/`paths:` on the workflow's own `on:` trigger, which
leaves the check permanently "Pending" instead of reporting `skipped`.

**`molecule` and `compose-boot-test` are the exception** — don't require
them directly. Both use a matrix (one entry per changed role/app), and
when the matrix actually runs, each entry posts its own check name (e.g.
`molecule (apt)`), which varies by PR. There's no single name that's
guaranteed to post for every PR: the base job name (`molecule`) only
appears when the job is skipped entirely, never when it actually ran.
Require `matrix-jobs-gate` instead — it depends on both, runs
regardless of whether they were skipped (`if: always()`), and fails
only if either genuinely failed (not skipped). One fixed name, correct
for every PR shape.

## Deploy-ordering-check

Regression coverage for an incident where `ansible_host` (`inventory.yaml`)
was wired to resolve through a role-generated fact
(`secrets_generated`) without anything in CI ever exercising that chain
— every other check either bypasses `ansible_host` resolution entirely
or tests the `secrets` role against a synthetic inventory that never
touches the real one.

Runs the **real** `deploy.yaml` (not a copy) against
`inventory/ci-deploy-ordering-inventory.yaml`, a purpose-built inventory
that mirrors `inventory.yaml`'s `ansible_host` → `ddns_domain` →
`main_domain` → `secrets_generated` chain and its
`managed_hosts`/`controller` group split, while staying CI-safe:
`ansible_connection: local` everywhere, and `--tags` matching nothing
real so provisioning never runs — only secrets generation/propagation
and the `ansible_host` resolution it gates.

`ansible/inventory/**` in the trigger list covers `inventory.yaml` itself
plus `group_vars/all/main.yaml`/`secrets_registry.yaml` — deliberately
broad, since either is the shape of change that caused the original
regression. `pyproject.toml`/`uv.lock` are in the trigger list too: this
job runs the real playbooks through the uv-managed `ansible-core`, so an
`ansible-core` bump is exercised here as well as by
[Molecule](#molecule_helpers-is-repo-wide).

`restore.yaml` gets a second, separate step: it can't import
`bootstrap-secrets.yaml` as a leading play the way `deploy.yaml` does
(see [`disaster-recovery.md`](disaster-recovery.md#restore)), so this
step is the regression check for that two-file invocation pattern
specifically — not for `restore`'s own validation logic, which
[Molecule](molecule-testing.md) already covers. It deliberately points
at a nonexistent archive and asserts the failure is the expected
archive-not-found message, not an `ansible_host`/`secrets_generated`
resolution failure (that signature means the regression is back).

Manual secrets are pre-seeded as plain files under
`ansible/files/secrets/`, mirroring what `bootstrap_secrets.py` produces
— throwaway CI values, same non-secret status as
`ci-inventory/group_vars/all/ci_dummy_vars.yaml`.

## Docs drift check

`.github/scripts/check-doc-drift.py`, wired into `.config/.pre-commit-config.yaml`
as a local hook — no separate job of its own, it rides along inside
`pre-commit-checks` above like every other commit-stage hook. Checks four
narrow, structural things:

- Every `docs/*.md` file is linked somewhere in README.md (both
  directions — a link to a deleted file fails too).
- `docs/ansible.md`'s Playbooks and Roles tables list exactly the files
  under `ansible/playbooks/*.yaml` and directories under
  `ansible/roles/*/`.
- `docs/molecule-testing.md`'s Scenario matrix table lists exactly the
  scenario directories that exist under `ansible/roles/*/molecule/*/`.
- `docs/deployment-flow.md` has one `## Play N` heading per play in
  `deploy.yaml`, numbered sequentially — title *wording* isn't compared,
  only count and sequence, so a heading paraphrasing a play's name isn't
  flagged as drift.
- This file's own Jobs table lists every `pr-checks.yml` job id, except
  `detect-changes` (internal plumbing) and `trivy-scan` (documented in
  [`security-scanning.md`](security-scanning.md) instead).

Deliberately presence/shape checks, not content review — it can't tell
you a description is *wrong*, only that something's missing or a
documented thing no longer exists.

## Molecule coverage gate

Each `molecule` matrix job regenerates that role's task inventory
(`molecule-coverage/inventory.py`, gitignored - tied to the checkout's
absolute paths, so not committed) and runs `report.py --thresholds-file
molecule-coverage/thresholds.yaml`, both against the coverage data that
role's own `molecule test` run just produced. Per-role, not one global
number, since roles aren't structurally comparable - see
[`molecule-coverage/README.md`](../ansible/molecule-coverage/README.md)
for what the report actually measures.

A role with no entry in `thresholds.yaml` fails the check (exit 2, not a
silent pass) - a new role needs a deliberate floor, not an inherited
default. Every floor is hand-verified against a real run, not a guess -
the below-100% floors are legitimate, understood gaps rather than
untested code (see [`thresholds.yaml`](../ansible/molecule-coverage/thresholds.yaml)
for the current values):

- `apt` - the reboot-if-required task needs rebooting the test
  container itself to exercise.
- `bind9` - the resolv.conf-upstream task needs a pre-existing
  non-upstream resolv.conf to be worth simulating.
- `restore` - the interactive confirmation prompt is bypassed on
  purpose in every scenario, to test the rest of the role
  non-interactively.

## Compose boot-test

Shared logic lives in `_compose-boot-test.yml` (`workflow_call`), used
by both `pr-checks.yml` (changed apps only) and `boot-test-all.yml`
(every app, `workflow_dispatch` only — a manual "test everything" run).

Per app: seeds it via the real `compose` role
(`ansible/playbooks/ci_boot_test.yaml`, against `ci-inventory/` rather
than the real `inventory.yaml`, since the latter's `all:vars` assumes a
real remote host), brings the stack up with `docker compose`, waits for
a healthy state (or that it stayed running, if no healthcheck is
defined), dumps logs on failure, then tears down.

**Excluded** (`.github/compose-boot-test-exclusions.txt`, shared by both
workflows and `pr-checks.yml`'s `compose-syntax-check` fallback):

- `bind9`, `seaweedfs`, `caddy` — covered by Molecule with stronger,
  real-protocol assertions than a healthcheck poll would add:
  `bind9`/`caddy` by their own role's scenario, `seaweedfs` by
  `seaweedfs_bucket`'s and `backup_agent`'s (see
  [`#molecule_helpers-is-repo-wide`](#molecule_helpers-is-repo-wide)).
- `tinyauth` — same category: `tinyauth/molecule/default` stands up a
  real, throwaway lldap target, runs `lldap_bootstrap` against it (see
  [`lldap.md`](lldap.md#bootstrapping-the-observer-account)), then
  deploys tinyauth pointed at it and confirms it reaches a healthy,
  LDAP-bound state — the dependency chain compose-boot-test's per-app
  isolation can never provide, since no `lldap` host exists to resolve
  in that model.

`lldap` is no longer in that list: `_compose-boot-test.yml` issues a real
cert for it from a throwaway `smallstep/step-ca` container (the official
image, driven by its own stock `DOCKER_STEPCA_INIT_*` auto-init — not
`docker/step-ca`'s own compose stack, which this CA only needs to
outlive a single job step, not persist), using the same `step ca
certificate` call `lldap_cert`'s real Ansible task runs — see
[`seed-lldap-ci-cert.sh`](../.github/scripts/seed-lldap-ci-cert.sh). This
exercises the real issuance path end to end rather than a parallel,
independently-authored openssl fixture, and needs no real DigitalOcean
credential or step-ca password — the throwaway CA and its password exist
only for this job's lifetime.

Excluded apps still get `compose-syntax-check`'s weaker
`docker compose config --quiet` validation, so nothing goes fully
unchecked.

## Trivy security scans

Report-only Ansible-misconfig and secret scanning, separate from the
correctness/linting jobs above — see
[`security-scanning.md`](security-scanning.md).
