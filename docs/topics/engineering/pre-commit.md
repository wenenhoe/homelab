# Linting and Pre-commit

## Installing the hooks

`pre-commit install` installs the `pre-commit`, `pre-push`, `post-checkout`,
`post-merge` and `post-rewrite` git hooks in one step
(`default_install_hook_types` in the config): most hooks run at commit time. `ansible-lint` runs at push time since it
always re-lints the whole `ansible/` tree rather than just what changed,
and so does `check-doc-change-push`, which needs the commits a push adds. `land_series` mirrors both stages without depending on these being installed: its replay runs the `pre-commit`-stage hooks for each commit, and `--land` runs the `pre-push` ones before each push and then pushes with hooks off ([`landing-a-series.md`](landing-a-series.md#landing)).
`.pre-commit-config.yaml` at the repo root is a symlink to
`.config/.pre-commit-config.yaml` (config lives under `.config/`, but
`pre-commit` only ever looks for its own config at the repo root by
default — no `-c` flag needed for this or `pre-commit run`, and nothing
lints the symlink itself, only real `.yaml` files). To run everything
manually regardless of stage: `pre-commit run --all-files --hook-stage
pre-commit` and `... --hook-stage pre-push`.

The generated views (the decision index, the planning view and the disaster-recovery coverage table) are not committed. `generate-doc-indexes` writes them, at commit time and also after a checkout, a merge and a rebase, so a clone has them current after any of those. A fresh clone has no hooks yet, so run `pre-commit run generate-doc-indexes` once after `pre-commit install`. `post-checkout` also runs when `git worktree add` makes a worktree, and `post-rewrite` after a rebase or an amend; a rebase checks out its new base once at the start and not at the end, so `post-rewrite` is what brings the views up to date with the rebased branch.

## Applying patches with `git am`

`git am` commits without running the `pre-commit` hook. A series is replayed with `git am` in a scratch worktree
([`landing-a-series.md`](landing-a-series.md)), which runs the checks after each commit, and a change to the tool that does it is applied by hand
with `git am`, then checked with `pre-commit run --all-files`. The generated views are not committed, so a patch holds only the change to what
they are written from, and two series that each add a project or a decision never conflict on them. A view's title and introduction are the
files in [`tools/doc_scripts/view_intros/`](../../../tools/doc_scripts/view_intros), which travel in a patch like any other file.

Two decision lineages with the same number fail `generate-doc-indexes`, so the checks the replay runs after the commit stop the series;
rewrite the patches with the [renumber helper](../documentation/project-checks.md#renumbering-a-patch-series-lineages) and apply the copies.

Plain patches (a change to `tools/land_series`, and the security series) are named with a letter on every
one (`0001a`, `0001b`, `0002a`): a follow-up to `0001a` is `0001b`, and plain `ls` and `git am *.patch`
order them the same way under the C and `en_US.UTF-8` locales. The security series uses `S0001a`. The ids in
a series file mean something else: a number is a pull request and each letter a commit in it
([`landing-a-series.md`](landing-a-series.md#the-input)).

## Hooks

`.config/.pre-commit-config.yaml` wires up:

- `check-yaml`, `end-of-file-fixer`, `trailing-whitespace` — general hygiene; `end-of-file-fixer` skips `tools/doc_site/vendor/`, whose stylesheet is kept as published so its pinned hash holds ([`doc-site.md`](../documentation/doc-site.md#the-stylesheet))
- [`gitleaks`](https://github.com/gitleaks/gitleaks) — secret scanning of what is staged; CI skips the hook and scans the PR's commits instead, see [Secret scanning on pull requests](security-scanning.md#secret-scanning-on-pull-requests)
- [`yamllint`](https://github.com/adrienverge/yamllint) — strict YAML style checks (`.config/.yamllint`)
- [`dclint`](https://github.com/docker-compose-linter/pre-commit-dclint) — lints/auto-fixes every `compose*.yaml`
- [`hadolint`](https://github.com/hadolint/hadolint) — lints every `Dockerfile`, via its Docker-image variant
- [`shellcheck`](https://github.com/shellcheck-py/shellcheck-py) — lints every `*.sh`
- [`actionlint`](https://github.com/rhysd/actionlint) — lints every `.github/workflows/*.yml`: expression types, `needs`/`outputs` wiring, script injection via untrusted `${{ }}` in `run:`, and `shellcheck` over inline `run:` blocks. Runs via its Docker-image variant (`.config/.actionlint.yaml`). Composite actions under `.github/actions/` aren't covered — it only parses workflow files
- [`zizmor`](https://github.com/zizmorcore/zizmor-pre-commit) — static analysis of `.github/workflows/*.yml` and composite `action.yml` files for credential persistence on checkout, expression injection into `run:`, and over-broad token permissions, among others (`.config/zizmor.yml`, which disables `self-repository`: it asks for the `$/` local-reference syntax, which the pinned actionlint rejects). CI sets `ZIZMOR_GITHUB_TOKEN` on the `pre-commit-checks` step so the audits that query GitHub also run; locally it stays offline unless that variable is exported
- `generate-doc-indexes` (local) — writes `docs/project-planning.md` and `docs/decision-index.md` from each doc's YAML frontmatter, and the coverage table in `docs/topics/disaster-recovery/coverage.md` from the app catalog, none of them committed, at commit time and after a checkout, a merge and a rebase; runs before the two hooks below so a bad generation is caught the same way a bad hand-edit would be — see [`tools/doc_scripts/generate_doc_indexes.py`](../../../tools/doc_scripts/generate_doc_indexes.py)
- [`markdownlint-cli2`](https://github.com/DavidAnson/markdownlint-cli2) — lints every `*.md`
- `check-doc-drift` (local) — keeps `ansible.md`, `molecule-testing.md`, `deployment-flow.md` and `ci/pipeline.md` in sync with the roles, playbooks, scenarios, and CI jobs they describe, and validates every doc's frontmatter, the decision-lineage and project rules, and every `docs/decisions/`/`docs/projects/` path written anywhere — see [`tools/doc_scripts/check_doc_drift.py`](../../../tools/doc_scripts/check_doc_drift.py)
- `check-moved-files` (local) — no file names a file that git history shows was renamed or removed, except the noted first mention in a decision revision; it reads the whole history and the whole tree, so it needs a full clone — see [`tools/doc_scripts/check_moved_files.py`](../../../tools/doc_scripts/check_moved_files.py)
- `check-retired-numbers` (local) — no file names a decision number that was merged into another lineage or listed in `removed.md`, as `ADR NNNN` in prose or a comment, or as the visible number of a link to another record; it reads the whole tree and needs no history — see [`tools/doc_scripts/check_retired_numbers.py`](../../../tools/doc_scripts/check_retired_numbers.py)
- `check-doc-change` (local) — the project scope, close and start checks and the accepted-records check, on what is staged; CI runs the same over the whole PR. The rules are in [the doc checks](../documentation/project-checks.md#the-four-project-and-record-checks-as-one-command) — see [`tools/doc_scripts/check_doc_change.py`](../../../tools/doc_scripts/check_doc_change.py)
- `check-doc-change-push` (local, push time) — the same four checks over the commits being pushed, against the default branch as the `project-checks` job does, so a stray file in an earlier commit or a missing `Editorial-Fix:` trailer shows before CI; it skips and says so when the clone has no default branch or shares no history with it — see [`tools/doc_scripts/check_doc_change.py`](../../../tools/doc_scripts/check_doc_change.py)
- [`ruff`](https://github.com/astral-sh/ruff-pre-commit) — lints (auto-fixing) and formats every `*.py`

All of the above run at commit time except `check-doc-change-push`, which runs at
push time. [`ansible-lint`](https://github.com/ansible/ansible-lint)
(lints `ansible/`; `docker/` excluded, it's Compose files not playbooks)
runs at **push** time too — it always re-lints the whole `ansible/`
tree regardless of what changed, so it's too slow to pay on every commit.

All tool configs live under `.config/` (each hook is passed an explicit
`-c` flag, since these tools don't auto-discover configs there by
default). `ansible-lint` also gets `--project-dir ansible`, since it
resolves `roles_path` relative to cwd rather than the config file.
`ruff` is one exception — its config lives in `pyproject.toml` at
the repo root, which it finds on its own, so no `-c` flag or
`.config/` entry exists for it. `hadolint` is another: its accepted-risk
findings are per-file, so they're justified inline with
`# hadolint ignore=DLxxxx # reason` comments next to the line they apply
to (`docker/caddy/Dockerfile`, `docker/molecule-dind/Dockerfile`) rather
than a repo-wide `.config/` ignore list. `shellcheck` is the third: no
args and no `.config/` entry either, since the repo's `.sh` scripts are
already clean at its default severity — a future finding worth
suppressing would get the same per-line treatment as `hadolint`'s
(`# shellcheck disable=SCxxxx # reason`), not a repo-wide config.

Run `pre-commit install` once after
cloning. CI enforces the same checks on every PR regardless of whether
hooks are installed locally — see [`ci/pipeline.md`](ci/pipeline.md).
