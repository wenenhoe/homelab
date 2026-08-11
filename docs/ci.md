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
`pre-commit-checks` and `ansible-lint` are the exception — they run
unconditionally on every PR regardless of what changed, since any file
could be touched by one of their hooks:

- `roles` — any `ansible/roles/<role>/` touched maps to that role, except
  `ansible/requirements.yml` (or its `molecule_helpers` copy), a
  repo-wide collection bump that maps to every role.
- `compose_apps` — any `docker/<app>/compose.yaml` touched, minus the
  exclusion list (below).
- `deploy_ordering` — `ansible/inventory/**`, `ansible/playbooks/**`,
  `ansible/roles/secrets/**`, `ansible/roles/restore/**`.
- `uv_lock` — `pyproject.toml`/`uv.lock` changed.

## Jobs

| Job | Runs when | What it does |
| :--- | :--- | :--- |
| `pre-commit-checks` | always | Every commit-stage hook (all of `.config/.pre-commit-config.yaml` except `ansible-lint`) against every file. |
| `ansible-lint` | always | `ansible-lint`, the one push-stage hook — always lints the whole `ansible/` tree, not just what changed, so it's pinned to push time locally too (see `.config/.pre-commit-config.yaml`). |
| `uv-lock` | `pyproject.toml`/`uv.lock` changed | `uv sync --locked` — catches an unregenerated lockfile or a resolvable-but-broken dependency combination. |
| `deploy-ordering-check` | inventory/playbooks/secrets/restore changed | See below. |
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
default. The current floors are hand-verified, not guesses - the three
below 100% are legitimate, understood gaps rather than untested code:

- `apt` (75%) - the reboot-if-required task needs rebooting the test
  container itself to exercise.
- `bind9` (94.4%) - the resolv.conf-upstream task needs a pre-existing
  non-upstream resolv.conf to be worth simulating.
- `restore` (92.9%) - the interactive confirmation prompt is bypassed on
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

- `bind9`, `seaweedfs`, `caddy` — already covered by their own Molecule
  scenarios with stronger, real-protocol assertions than a generic
  healthcheck poll would add.
- `lldap` — `certbot` needs a real DigitalOcean DNS-01 credential to do
  anything meaningful, and `lldap` itself has no healthcheck defined yet.
- `tinyauth` — crashes on boot with a config-loading error despite a
  live-verified, schema-correct config; not yet root-caused.

Excluded apps still get `compose-syntax-check`'s weaker
`docker compose config --quiet` validation, so nothing goes fully
unchecked.

## Trivy security scans

Three independent Trivy checks, defined once in
[`_trivy-scan.yml`](../.github/workflows/_trivy-scan.yml) (`workflow_call`,
same sharing pattern as `_compose-boot-test.yml`) and run from two
places:

- `pr-checks.yml`'s `trivy-scan` job — image CVE and Ansible misconfig
  scoped via `detect-changes` (`any_compose`/`trivy_ansible`); the secret
  scan runs unconditionally on every PR, the same reasoning as
  `pre-commit-checks` (a leaked secret can land in any file). It's a
  second, independent backstop alongside `gitleaks`, which
  `pre-commit-checks` already runs unconditionally.
- `trivy-scheduled.yml` — all three, weekly, unscoped, so a CVE disclosed
  in an already-deployed image or a new misconfig check added to Trivy
  itself still gets caught even when nothing in this repo changed.

| Check | Target | Notes |
| :--- | :--- | :--- |
| Image CVE | Every `image:` in `docker/**/compose*.yaml` (~15 images), full set every run | `HIGH,CRITICAL` only, `image.source: [remote]` forced (see below) |
| Ansible misconfig | `ansible/` (Trivy's ansible scanner auto-detects the project root via `ansible.cfg`, `roles/`, `playbooks/`, etc.) | `--misconfig-scanners ansible` only, via an inline `trivy.yaml` (`misconfiguration.scanners`) — trivy-action has no first-class input for this flag |
| Secrets | Whole repo (`trivy fs --scanners secret`) | Second, independent backstop alongside `gitleaks` (already unconditional in `pre-commit-checks`) |

**Image scans always hit the registry, never a local cache**: Trivy's
default image-source order is `docker,containerd,podman,remote` — it
prefers a locally-cached image over the registry if one happens to
exist under that exact `name:tag`. The CI job forces `image.source:
[remote]` explicitly. This matters most if you ever re-run an image
scan by hand on this repo's **controller** rather than in CI — the
controller runs Docker locally (needed for `molecule`), so a local
`trivy image <ref>` there can silently report on a stale cached image
instead of what's actually published, with no indication in the output
that it happened. Pass `--image-src remote` on the CLI to get the same
guarantee locally.

**Report-only for now**: every job sets `exit-code: '0'` — findings
surface but don't block the PR. Flip to `'1'` (with a `severity:` filter,
for the image scan) once the backlog from the first few runs has been
triaged.

**Where findings go**: SARIF, uploaded to the repo's Security > Code
Scanning tab via `github/codeql-action/upload-sarif`, one `category` per
scan (`trivy-image-<name>` per image, `trivy-ansible-misconfig`,
`trivy-secrets`) so results don't collide in the UI.

**Accepted-risk findings**: [`.config/.trivyignore`](../.config/.trivyignore),
alongside this repo's other tool configs, one shared file across all
three scans — same documented-exception convention as
`.github/compose-boot-test-exclusions.txt`.

**Two confirmed Trivy Ansible-scanner quirks** (v0.73.0; re-verify if a
version bump ever changes this):

- It never reads `ansible.cfg`'s `roles_path` — role resolution
  (`resolveRolePath` in `pkg/iac/scanners/ansible/parser/parser.go`)
  only checks a `roles/` dir next to the playbook file, or the
  `DEFAULT_ROLES_PATH` env var. This repo's roles are a sibling of
  `ansible/playbooks/`, not nested under it, so without
  `DEFAULT_ROLES_PATH` every `include_role`/`roles:` silently fails to
  resolve and the scan reports a clean pass while covering almost none
  of the real task content.
- Playbook auto-discovery (`resolvePlaybooksPaths`) only lists YAML
  files in the project root — a non-recursive `ReadDir()` — so it never
  finds anything under `playbooks/`. Worked around the same way: an
  explicit `ansible.playbooks` list in the generated `trivy.yaml`, built
  from the live `ansible/playbooks/*.y{a,}ml` listing so a new playbook
  is covered automatically.

With both fixed, this repo currently scans clean — expected: Trivy's
Ansible module analysis only checks cloud-resource modules, and this
repo's roles use `community.docker`/`ansible.posix`/`ansible.builtin.*`
exclusively. The job is still the regression backstop it was scoped as —
it would catch a misconfigured cloud module if one is ever added.
