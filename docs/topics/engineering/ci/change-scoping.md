# CI Change Scoping

How `detect-changes` decides which jobs a PR queues: the scoped outputs it feeds them, each Molecule role's watch set, and the comment-only and formatting-only changes that queue nothing. The jobs and how they fit together are in [CI: PR Checks](pipeline.md#jobs).

## Change-scoped, not a full sweep

`detect-changes` diffs the PR's base/head and feeds most other jobs a
scoped input, so a docs-only PR doesn't trigger Molecule or boot-tests.
`pre-commit-checks` is the exception — it runs unconditionally on every
PR regardless of what changed, since its hooks span nearly every file
type in the repo:

- `roles` — each role with a `molecule/` scenario is queued when a
  changed file sits in that role's *watch set*: its own directory, plus
  everything its scenarios read from outside it. Derived from the tree
  on every run, so it can't drift — see
  [`#molecule-watch-sets`](#molecule-watch-sets). A few paths still map
  to *every* role: `ansible/requirements.yml` (a Galaxy collection
  bump), `pyproject.toml`/`uv.lock` (pins the `ansible-core` version every
  role's Molecule run actually executes under), `.config/molecule/`, and
  everything that base config points every scenario at: `molecule_helpers/`'s
  two requirements files, `ansible/ansible.cfg` and the coverage callback
  plugin under `ansible/molecule-coverage/callback_plugins/`. The last
  group is read from the config, not listed (see
  [Molecule watch sets](#molecule-watch-sets)).
- `compose_apps` — any `docker/<app>/compose.yaml` or `compose.yaml.j2`,
  its `Dockerfile`, or any file under `docker/<app>/configs/` or
  `docker/<app>/scripts/`, touched, minus the exclusion list.
  A directory with no compose file isn't an app. All of it is
  [`tools/ci/scope/compose_apps.py`](../../../../tools/ci/scope/compose_apps.py),
  the one reader of the exclusion list (see
  [Compose boot-test](gates.md#compose-boot-test)). The `compose` role renders and stages `configs/` and `scripts/` before
  the stack boots, and `compose-boot-test` builds the `Dockerfile` in
  place of the published image, so a change to any of them alters what
  it actually exercises.
- `dockerfiles` — any `docker/<app>/Dockerfile` touched, excluded apps
  included. See [Dockerfile changes](gates.md#dockerfile-changes).
- `deploy_ordering` — `ansible/inventory/**`, `ansible/playbooks/**`,
  `ansible/roles/secrets/**`, `ansible/roles/restore/**`,
  `tools/ci/gates/deploy_ordering.py`, `tools/ci/fixtures/**`,
  `pyproject.toml`/`uv.lock`.
- `uv_lock` — `pyproject.toml`/`uv.lock` changed.
- `python_unit_tests` — `ansible/scripts/*.py`,
  `tools/cloud_credentials/**`,
  `tools/openbao_utils/**`, `tools/utils/**`, `tools/ci/**`,
  `tools/doc_scripts/**`,
  `ansible/molecule-coverage/molecule_cov/**`,
  `ansible/molecule-coverage/callback_plugins/**`, `ansible/tests/**`,
  `tools/tests/**`, `docker/openbao/watcher/r2_read_watcher.py`,
  `pyproject.toml`/`uv.lock`. This is all plain controller-side Python,
  not Ansible roles, so it's covered by `ansible/tests/`'s and
  `tools/tests/`'s `pytest` suites instead of Molecule — including
  `r2_read_watcher.py`, the one file outside either tree that
  `ansible/tests/` imports directly, through the `pythonpath` in
  `pyproject.toml`'s `[tool.pytest]`.

### Molecule watch sets

`tools/ci/scope/molecule_scope.py` (run by `detect-changes`, tested in
`tools/tests/ci/scope/`) builds each role's watch set from what its
scenarios actually reference, then queues a role when a changed file
falls inside it:

- the role's own directory;
- every role it runs: `include_role`/`import_role` names, play `roles:`
  entries and `meta` dependencies in the scenario's playbooks, the
  role's own tasks/handlers/meta, and each included role's in turn. The
  whole included role's directory is watched, so a change to `compose`
  queues every role whose Molecule run exercises it, not just
  `compose`'s own scenarios. A role with no scenario of its own (like
  `molecule_helpers`, or a shared role nothing tests directly) is
  watched but never queued;
- each filter plugin in `ansible/filter_plugins/` that defines a filter
  named in any of the files this watch set already covers (`| cron_period_hours`,
  or the bare name in `map('...')`), so editing a filter queues the roles
  that call it and not every role. The names are read from the dict literal
  `FilterModule.filters()` returns, without importing the plugin, and must
  stand alone: `compose_app_deploy_plan` is not a use of `app_deploy_plan`;
- each `molecule_helpers` task file a scenario pulls in with
  `include_role: {name: molecule_helpers, tasks_from: ...}`, followed
  through the helper playbooks and task files that include further
  helper task files or roles (`resolve_compose_apps.yaml` runs
  `compose`'s `preinit.yaml`, so its consumers watch `compose` too, and it
  names the `resolve_apps` filter, so they watch that plugin and no other
  scenario does);
- each `${MOLECULE_PROJECT_DIRECTORY}/...` path in a scenario's
  `molecule.yml` (the shared `prepare` playbooks);
- the target of every symlink under `molecule/`. Scenarios link the
  real `docker/<app>/` files and `molecule_helpers/fixtures/` into
  their own `files/`, and git reports the target path, not the link;
- files read by a path built from `playbook_dir`, which is the
  scenario directory under Molecule: `playbook_dir ~ '/../x'`,
  `{{ playbook_dir }}/../x`, and the same through any variable a
  scenario defines as `{{ playbook_dir }}` or
  `{{ (playbook_dir ~ '...') | realpath }}` (`project_root`,
  `repo_root`), whether the path is written in the scenario or in the
  role's own tasks and templates. The target need not exist: deleting a file
  a scenario reads still queues that scenario. A variable used only as a base
  directory (`project_root ~ '/ansible/files/key.asc'`) contributes the files
  it is joined to, not the directory its definition names, so a role that
  defines one doesn't end up watching everything under it. This is how
  `inventory/group_vars/all/app_catalog.yaml`, `ansible/scripts/restore_all.py`,
  `docker/openbao/policies/controller.hcl` and
  `docker/seaweedfs/configs/s3-identity.json.j2` reach the scenarios
  that read them.

### Comments and formatting don't queue Molecule

Before any of that matching, `detect-changes` drops a changed file whose
*parsed* content is identical in base and head
(`tools/ci/scope/semantic_diff.py`). A comment added, edited or
removed, or a reformat (indentation, quoting, blank lines), queues no
role, and doesn't trip the repo-wide or `molecule_helpers` fail-safes
either. The log line says `comments/formatting only -> ignored`.

The same rule gates three of the path-filter outputs
(`tools/ci/scope/effective_changes.py`): `uv_lock`, `deploy_ordering`
and `python_unit_tests` are true only if at least one file the filter
matched changed for real. The filter step lists its matched files
(`list-files: json`), and the `effective` step checks each one. So a
comment in a test, or an edit to `[tool.ruff]`, no longer starts
`python-unit-tests`, `uv-lock` or `deploy-ordering-check`. `ansible_lint`,
`trivy_ansible` and `any_compose` are never gated, and the script
refuses to: ansible-lint honours `# noqa`, Trivy honours
`#trivy:ignore`, and compose files are never a no-op.

It compares what the parser produces, not the text, so a `#` line
inside a YAML block scalar (a script or config written into a file) is
data and counts as a real change. Only files whose parser is the
consumer are eligible:

- YAML that Ansible, `ansible-galaxy` or Molecule loads: a role's
  `tasks/`, `handlers/`, `defaults/`, `vars/`, `meta/`; a scenario's
  own playbooks, `molecule.yml` and `host_vars/`/`group_vars/`;
  `molecule_helpers`' playbooks and requirements files;
  `ansible/requirements.yml`; `ansible/playbooks/`, `inventory/` and
  `ci-inventory/`; `.config/molecule/`. YAML shipped as content (a
  compose fixture, a file copied to a host) is not, since a comment
  there can mean something to whatever reads it (`#cloud-config`).
- Python, compared as its AST plus the shebang and any `coding:` line,
  which the interpreter reads. A docstring is code.
- `pyproject.toml` and `uv.lock`, compared as parsed TOML.
  `pyproject.toml` is compared without `[tool.ruff]`, which only
  configures a linter `pre-commit-checks` runs over every file anyway.
  Every other table counts, including one added later, so an unknown
  table errs toward running the checks.

Anything else (`.j2` templates, shell, compose files), a file added or
deleted, a file that doesn't parse on either side, and a mode-only
change are real changes. Everything not named above keeps its path-based trigger, so
`ansible-lint`, `trivy-scan` and `pre-commit-checks` still see a
comment-only change (a comment can be a `# noqa`, `# yamllint disable`
or `#trivy:ignore`).

`ansible/roles/molecule_helpers/` isn't a normal role — it has no
`molecule/` scenario of its own — so a change there queues only the
roles whose watch set contains that file. Three fail-safes always queue
*more*: a changed file under `molecule_helpers/` that no scenario
references queues every role (a *deleted* one queues nothing: no scenario
names it, or the scan would have failed, and a reference removed in the same
change is in a scenario file that changed with it); a changed file under
`ansible/filter_plugins/` whose filter names can't be read (deleted, a helper
module, a plugin that builds `filters()` any way but a dict literal, or
anything nested or not `.py`) queues every role, since there is no telling who
called it, while a readable plugin no role calls queues nothing; and so does
any repo-wide path: `GLOBAL_PATHS`
plus every path in `.config/molecule/config.yml`, the base config deep-merged
into every scenario, written as `${MOLECULE_PROJECT_DIRECTORY}/...`. Those
are resolved from the config on each run (`base_config_paths`), so pointing
`ANSIBLE_CONFIG` or `ANSIBLE_CALLBACK_PLUGINS` somewhere else moves the
trigger with it. Left out: the roles directory (the per-role watch sets
already cover it) and the gitignored coverage output directory. The
coverage thresholds file and the `molecule_cov` gate package are read after
the scenarios run, by the gate, so they don't queue any role; `pytest` covers
`molecule_cov`. A reference the scanner can't resolve (a templated `include_role` name, a
role that isn't a directory under `ansible/roles/`, a dangling symlink,
a `tasks_from` naming no file) fails `detect-changes` rather than being
skipped. Each queued role's log line in `detect-changes` names the
changed file and why it matched.

Not modelled: paths built any other way (a variable not defined as
above, or a literal continued with `~`), which are ignored, as are
computed paths that leave the repo or are the role's own directory or an
ancestor of it. Roles are watched whole-directory
rather than by `tasks_from`, so a change to any file in an included
role queues its consumers.

Because a scenario that links `docker/seaweedfs/` files is queued when
they change, the `seaweedfs` `compose-boot-test-exclusions.txt` entry
in [Compose boot-test](gates.md#compose-boot-test) stays correct — see there for the SeaweedFS-specific case.

`detect-changes` runs the scanner with `uv run python -m ci.scope.molecule_scope` from `tools/`, so it sets up uv
(no `needs:` on `warm-uv-cache`, and unlocked, for the reasons under
[Cache warming](pipeline.md#cache-warming)).
