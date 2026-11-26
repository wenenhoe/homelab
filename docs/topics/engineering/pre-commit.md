# Linting and Pre-commit

## Installing the hooks

From the repository root:

```bash
pre-commit install
pre-commit run generate-doc-indexes
```

The first installs the `pre-commit`, `pre-push`, `post-checkout`, `post-merge` and `post-rewrite` git hooks (`default_install_hook_types`). The second writes the generated views, which a fresh clone lacks. To run everything by stage, or one hook by id:

```bash
pre-commit run --all-files --hook-stage pre-commit
pre-commit run --all-files --hook-stage pre-push
```

```bash
hook=check-command-blocks
pre-commit run "$hook" --all-files
```

Most hooks run at commit time. `ansible-lint` and `check-doc-change-push` run at push time: the first re-lints the whole `ansible/` tree, the second needs the commits a push adds. `land_series` runs both stages itself, installed or not ([`landing-a-series.md`](landing-a-series.md#landing)). The config is [`.config/.pre-commit-config.yaml`](../../../.config/.pre-commit-config.yaml), symlinked at the repository root so `pre-commit` finds it. CI runs the same checks on every pull request ([`ci/pipeline.md`](ci/pipeline.md)).

The generated views (the decision index, the planning view and the disaster-recovery coverage table) are not committed. `generate-doc-indexes` writes them, at commit time and also after a checkout, a merge and a rebase, so a clone has them current after any of those. `post-checkout` also runs when `git worktree add` makes a worktree, and `post-rewrite` after a rebase or an amend; a rebase checks out its new base once at the start and not at the end, so `post-rewrite` is what brings the views up to date with the rebased branch.

## Applying patches with `git am`

`git am` commits without running the `pre-commit` hook. A series is replayed with `git am` in a scratch worktree
([`landing-a-series.md`](landing-a-series.md)), which runs the checks after each commit, and a change to the tool that does it is applied by hand
with `git am`, then checked with `pre-commit run --all-files`. A patch holds none of the [generated views](#installing-the-hooks), so two series that each add a project or a decision never conflict on them. A view's title and introduction are the
files in [`tools/doc_scripts/view_intros/`](../../../tools/doc_scripts/view_intros), which travel in a patch like any other file.

Two decision lineages with the same number fail `generate-doc-indexes`, so the checks the replay runs after the commit stop the series;
rewrite the patches with the [renumber helper](../documentation/project-checks.md#renumbering-a-patch-series-lineages) and apply the copies.

Plain patches (a change to `tools/land_series`, and the security series) are named with a letter on every
one (`0001a`, `0001b`, `0002a`): a follow-up to `0001a` is `0001b`, and plain `ls` and `git am *.patch`
order them the same way under the C and `en_US.UTF-8` locales. The security series uses `S0001a`. The ids in
a series file mean something else: a number is a pull request and each letter a commit in it
([`landing-a-series.md`](landing-a-series.md#the-input)).

## Hooks

### Third-party

| Hook | Checks | Config |
| :--- | :--- | :--- |
| `check-yaml`, `end-of-file-fixer`, `trailing-whitespace` | general hygiene; `tools/doc_site/vendor/` is skipped so its [pinned hashes](../documentation/doc-site.md#the-stylesheet) hold | none |
| [`gitleaks`](https://github.com/gitleaks/gitleaks) | secrets in what is staged; CI scans the PR's commits instead ([secret scanning](../security/policy/security-scanning.md#secret-scanning-on-pull-requests)) | none |
| [`yamllint`](https://github.com/adrienverge/yamllint) | YAML style, strict | `.config/.yamllint` |
| [`dclint`](https://github.com/docker-compose-linter/pre-commit-dclint) | every `compose*.yaml`, fixing | `.config/.dclintrc` |
| [`hadolint`](https://github.com/hadolint/hadolint) | every `Dockerfile`, from its Docker image | inline `# hadolint ignore=` with a reason |
| [`shellcheck`](https://github.com/shellcheck-py/shellcheck-py) | `*.sh` and Bats files | inline `# shellcheck disable=` with a reason |
| [`actionlint`](https://github.com/rhysd/actionlint) | workflows (not composite actions): expression types, `needs` and `outputs` wiring, script injection, inline shell; from its Docker image | `.config/.actionlint.yaml` |
| [`zizmor`](https://github.com/zizmorcore/zizmor-pre-commit) | workflows and composite actions: persisted credentials, injection, broad permissions. The audits that query GitHub need `ZIZMOR_GITHUB_TOKEN`, which CI sets | `.config/zizmor.yml` (disables `self-repository`, which asks for syntax `actionlint` rejects) |
| [`markdownlint-cli2`](https://github.com/DavidAnson/markdownlint-cli2) | every `*.md` | `.config/.markdownlint.yaml` |
| [`ruff`](https://github.com/astral-sh/ruff-pre-commit) | `*.py`, lint with fixes and format | `pyproject.toml` |
| [`ansible-lint`](https://github.com/ansible/ansible-lint) (push) | `ansible/`; `docker/` is excluded | `.config/.ansible-lint`, `--project-dir ansible` |

Tool configs live under `.config/` and each hook is passed its path. `hadolint` and `shellcheck` have no repository-wide ignore list: a finding worth accepting is justified on its own line.

### Local

| Hook | Checks |
| :--- | :--- |
| `generate-doc-indexes` | writes the [generated views](#installing-the-hooks), before the checks that would catch a bad one ([`generate_doc_indexes.py`](../../../tools/doc_scripts/generate_doc_indexes.py)) |
| `check-doc-drift` | [docs match the code](../documentation/doc-checks.md#docs-drift-check), frontmatter and decision and project rules |
| `check-moved-files` | [no file names a renamed or removed file](../documentation/doc-checks.md#moved-file-check); needs a full clone |
| `check-retired-numbers` | [no file names a retired decision number](../documentation/doc-checks.md#retired-number-check) |
| `check-command-blocks` | [code fences and shell block rules](../documentation/doc-checks.md#command-block-check) |
| `check-doc-change`, `check-doc-change-push` (push) | the [project and record checks](../documentation/project-checks.md#the-four-project-and-record-checks-as-one-command) on what is staged, or on the commits pushed. The push form skips, saying so, without a shared default branch |
| `check-secret-catalog`, `check-app-catalog` | the [secret](ci/gates.md#secret-catalog-rules) and [app](ci/gates.md#app-catalog-rules) catalog rules |
| `check-compose-hardening`, `check-docker-container-hardening` | [compose](ci/gates.md#compose-hardening-rules) and [`docker_container`](ci/gates.md#docker_container-rules) hardening |
| `check-flow-list` | the [flow list rules](ci/gates.md#flow-list-rules) |
| `check-image-pins`, `check-image-digests`, `check-molecule-image-vars` | [image reference checks](ci/gates.md#checks-on-image-references) |
