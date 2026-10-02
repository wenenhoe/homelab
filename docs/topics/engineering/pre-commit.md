# Linting and Pre-commit

## Installing the hooks

`pre-commit install` installs both the `pre-commit` and `pre-push` git
hooks in one step (`default_install_hook_types` in the config): most
hooks run at commit time, and `ansible-lint` runs at push time since it
always re-lints the whole `ansible/` tree rather than just what changed.
`.pre-commit-config.yaml` at the repo root is a symlink to
`.config/.pre-commit-config.yaml` (config lives under `.config/`, but
`pre-commit` only ever looks for its own config at the repo root by
default — no `-c` flag needed for this or `pre-commit run`, and nothing
lints the symlink itself, only real `.yaml` files). To run everything
manually regardless of stage: `pre-commit run --all-files --hook-stage
pre-commit` and `... --hook-stage pre-push`.

## Hooks

`.config/.pre-commit-config.yaml` wires up:

- `check-yaml`, `end-of-file-fixer`, `trailing-whitespace` — general hygiene
- [`gitleaks`](https://github.com/gitleaks/gitleaks) — secret scanning
- [`yamllint`](https://github.com/adrienverge/yamllint) — strict YAML style checks (`.config/.yamllint`)
- [`dclint`](https://github.com/docker-compose-linter/pre-commit-dclint) — lints/auto-fixes every `compose*.yaml`
- [`hadolint`](https://github.com/hadolint/hadolint) — lints every `Dockerfile`, via its Docker-image variant
- [`shellcheck`](https://github.com/shellcheck-py/shellcheck-py) — lints every `*.sh`
- [`actionlint`](https://github.com/rhysd/actionlint) — lints every `.github/workflows/*.yml`: expression types, `needs`/`outputs` wiring, script injection via untrusted `${{ }}` in `run:`, and `shellcheck` over inline `run:` blocks. Runs via its Docker-image variant (`.config/.actionlint.yaml`). Composite actions under `.github/actions/` aren't covered — it only parses workflow files
- [`zizmor`](https://github.com/zizmorcore/zizmor-pre-commit) — static analysis of `.github/workflows/*.yml` and composite `action.yml` files for credential persistence on checkout, expression injection into `run:`, and over-broad token permissions, among others (`.config/zizmor.yml`, which disables `self-repository`: it asks for the `$/` local-reference syntax, which the pinned actionlint rejects). CI sets `ZIZMOR_GITHUB_TOKEN` on the `pre-commit-checks` step so the audits that query GitHub also run; locally it stays offline unless that variable is exported
- `generate-doc-indexes` (local) — regenerates the index tables in `docs/projects/README.md`, `docs/project-planning.md`, and `docs/decisions/README.md` from each doc's YAML frontmatter; runs before the two hooks below so a bad generation is caught the same way a bad hand-edit would be — see [`tools/doc_scripts/generate_doc_indexes.py`](../../../tools/doc_scripts/generate_doc_indexes.py)
- [`markdownlint-cli2`](https://github.com/DavidAnson/markdownlint-cli2) — lints every `*.md`
- `check-doc-drift` (local) — keeps `ansible.md`, `molecule-testing.md`, `deployment-flow.md` and `ci/pipeline.md` in sync with the roles, playbooks, scenarios, and CI jobs they describe, and validates every doc's frontmatter, the decision-lineage and project rules, and every `docs/decisions/`/`docs/projects/` path written anywhere — see [`tools/doc_scripts/check_doc_drift.py`](../../../tools/doc_scripts/check_doc_drift.py)
- `check-project-scope` (local) — a commit that touches a project doc stays inside that project's `allowed_paths`, read from `HEAD`; CI runs the same check over the whole PR — see [`tools/doc_scripts/check_project_scope.py`](../../../tools/doc_scripts/check_project_scope.py)
- `check-project-close` (local) — a commit that deletes a project doc leaves its `decision:` revision `accepted` or still named by another project, judged on what is staged; CI runs the same check over the whole PR — see [`tools/doc_scripts/check_project_close.py`](../../../tools/doc_scripts/check_project_close.py)
- [`ruff`](https://github.com/astral-sh/ruff-pre-commit) — lints (auto-fixing) and formats every `*.py`

All of the above run at commit time. [`ansible-lint`](https://github.com/ansible/ansible-lint)
(lints `ansible/`; `docker/` excluded, it's Compose files not playbooks)
runs at **push** time instead — it always re-lints the whole `ansible/`
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
