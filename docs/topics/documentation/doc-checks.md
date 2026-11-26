# Doc Checks

The hooks and jobs that keep the docs consistent with the files and config they describe. The checks on project and decision records are in [Project and Record Checks](project-checks.md); how all of them sit in the pipeline is in [CI: PR Checks](../engineering/ci/pipeline.md).

| Check | Module in [`tools/doc_scripts/`](../../../tools/doc_scripts) | Runs in | Needs history |
| :--- | :--- | :--- | :--- |
| [Index generation](#doc-index-generation) | `generate_doc_indexes` | pre-commit, post-checkout, post-merge, post-rewrite; CI | no |
| [Drift](#docs-drift-check) | `check_doc_drift` | pre-commit; CI | no |
| [Moved files](#moved-file-check) | `check_moved_files` | pre-commit; CI | yes |
| [Retired numbers](#retired-number-check) | `check_retired_numbers` | pre-commit; CI | no |
| [Command blocks](#command-block-check) | `check_command_blocks` | pre-commit; CI | no |
| [Mermaid render](#mermaid-render-check) | `check_mermaid` | the `mermaid-check` CI job | no |

In CI, the pre-commit checks run in [`pre-commit-checks`](../engineering/ci/pipeline.md#jobs). To run the four checks on the whole tree, from the repository root:

```bash
for hook in check-doc-drift check-moved-files check-retired-numbers check-command-blocks; do
  pre-commit run -c .config/.pre-commit-config.yaml "$hook" --all-files
done
```

## Doc index generation

[`generate_doc_indexes.py`](../../../tools/doc_scripts/generate_doc_indexes.py) reads every project and decision revision's frontmatter, validating it, and writes three views whole. The hook runs before markdownlint and the drift check, so a bad generation is caught by what follows.

| View | Sections |
| :--- | :--- |
| `docs/project-planning.md` | Roadmap, Super Projects, Projects, Decisions awaiting a project, Open explorations |
| `docs/decision-index.md` | By number, By topic, Open decisions, History |
| the coverage table ([`doc_coverage.py`](../../../tools/doc_scripts/doc_coverage.py)) | `## Apps`: each app's hosts, volumes, routes, backup, service record and recovery tier, from the app catalog and inventory. It reads no exercise result |

Each view's title and introduction come from [`view_intros/`](../../../tools/doc_scripts/view_intros). The views are git-ignored; the hook also runs after a checkout, merge or rebase so a clone has them. To write them by hand:

```bash
cd tools && uv run python -m doc_scripts.generate_doc_indexes
```

Nothing is stored for what the views compute:

- **Project tables:** the Unblocks counts, Status and Blocker cells, row order, and the approved-first order of decisions come from frontmatter alone.
- **Reliance:** the index's "Relies on" note, and a project's "rests on ADR-NNNN (state)" label while its revision has an unmet `relies_on:` ([ADR 0082 (Choosing the next project)](../../decisions/0082-choosing-which-project-to-take-up-next/revision-002.md)).
- **Roadmap:** a row per initiative in the numbered list under [`## Initiatives`](../../projects/README.md#initiatives), then one for projects with no `super_project`. A project is In progress (building or de-risking), Startable (not started, Blocker `—`) or Waiting; a done one is not shown. That list is the only stored order.

The generator writes nothing, naming each problem, when a `super_project` is missing from the list, an initiative is listed twice or unused, or two lineage directories share a number (see the [renumber helper](project-checks.md#renumbering-a-patch-series-lineages)). A stale view fails the commit and shows the diff.

## Docs drift check

[`check_doc_drift.py`](../../../tools/doc_scripts/check_doc_drift.py) checks presence and shape, not content: it cannot tell that a description is wrong, only that something is missing or a documented thing is gone.

### Indexes and reference tables

| Check | Fails when |
| :--- | :--- |
| Indexes | A doc under `docs/`, `docs/decisions/`, `docs/architecture/`, `docs/projects/` (one level) or `docs/topics/` (any depth, by relative path) is not linked in that directory's `README.md`, or the README links a missing file |
| Ansible tables | The Playbooks and Roles tables of [`ansible.md`](../deploy/ansible.md) do not list exactly the playbooks and role directories |
| Molecule matrix | The Scenario matrix of [`molecule-testing.md`](../testing/molecule-testing.md) does not list exactly the scenario directories |
| Deploy plays | The Plays table of [`deployment-flow.md`](../deploy/deployment-flow.md) lacks a row per play of `deploy.yaml`, numbered from 0. Wording is not compared |
| CI jobs | The [Jobs table](../engineering/ci/pipeline.md#jobs) misses a `pr-checks.yml` job other than `detect-changes` and `trivy-scan` |
| Service records | An `app_catalog` entry's `doc:` is missing, or the doc lacks a non-empty `Dependencies`, `Data`, `Exposure`, `Threat model`, `Observability`, `Disaster recovery` or `Lifecycle` section, in that order ([below](#service-records)) |
| NIST alignment | An ADR linked from [`nist-800-53-alignment.md`](../security/policy/nist-800-53-alignment.md) is `superseded` |
| Policy flow names | A row of the [zone policy](../infra/tofu/opnsense-gateway.md#zone-policy) lacks a unique flow name, a link to that section names no flow, or a doc linking the gateway doc cites a row by number ([`doc_policy_flows.py`](../../../tools/doc_scripts/doc_policy_flows.py)) |

### Links and mentions

| Check | Fails when |
| :--- | :--- |
| Anchors | A `#anchor` reference anywhere, YAML and Python comments included, has no heading that slugs to it |
| Relative files | A `./` or `../` link from markdown to a config, script or data file does not resolve |
| Record paths | A `docs/decisions/` or `docs/projects/` `.md` path written anywhere, comments included, does not exist. A path containing `NNN` is a placeholder; name a deleted file without its path |
| View and site links | A generated view is linked by file path (views may link each other), or a link to the site names no page, heading or section ([linking a view](doc-site.md#linking-a-view)) |
| Lineage names | A link reading `[ADR 0044 (CD agent trigger)]` does not carry the lineage's `short:` name. A number alone is not checked ([citing](../../decisions/README.md#citing-a-decision)) |
| Stage words | Outside projects, decisions and explorations, one paragraph, item or row both uses a stage, phase or track word and links a project or names a `PROJ-` id ([`doc_stage_words.py`](../../../tools/doc_scripts/doc_stage_words.py)). The vocabulary is deleted with the project |
| Explorations | The frontmatter lacks `type: exploration`, `status: open`, `topic` or an `id` of `EXP-` plus the file name, `related` names no real lineage, or a file outside the directory (but the planning view) names an [exploration](../../explorations/README.md) |

### Decision records

| Check | Fails when |
| :--- | :--- |
| Lineages | A lineage breaks [its rules](../../decisions/README.md#lineages-and-revisions) or [states](../../decisions/README.md#revision-states): a missing generation or letter, two `accepted` or `approved`, a `superseded` revision without a successor that declares it back, `title`, `short` or `topic` differing between revisions, a repeated `short`, a bad `narrows`, `related` or `former_ids`, or a lineage absent from the index |
| Headings | An unlettered revision 0 does not open `# NNNN. <title>`, or a revision has a `**Status:**` line |
| Assumptions | An `approved` or `accepted` revision has a bullet under `Assumptions` ([the gate](../../decisions/README.md#assumptions)) |
| Weight | `weight` is not `full` or `light`, or a `light` revision has a forbidden section or exceeds `LIGHT_MAX_WORDS` ([weights](../../decisions/README.md#weights)) |
| Superseded shape | A `superseded` revision has a section beyond [the frozen ones](../../decisions/README.md#superseded-revisions) |
| Removed ledger | A [`removed.md`](../../decisions/removed.md) row is malformed, repeats, or names a number that a lineage holds or lists in `former_ids` |

### Projects

| Check | Fails when |
| :--- | :--- |
| Status | A project's `decision:` revision is not in the state its status needs, or its status disagrees with its stage table ([lifecycle](../../projects/README.md#lifecycle)). A project without `decision:` is not gated |
| Dependencies | `depends_on` names a missing project or itself, or forms a cycle |
| Non-build stages | A stage matching `STAGE_KINDS` in `doc_scope.py` is not `Done` ([what a stage is](../../projects/README.md#what-a-stage-is)) |
| Plan | A project whose decision is `working` lacks `plan: draft` |

### Reliance, warnings and fixing

A declared `relies_on:` is met when an `approved` revision's target has an `approved` or `accepted` revision, or an `accepted` revision's target an `accepted` one ([relying on a lineage](../../decisions/README.md#relying-on-another-lineage), [`doc_reliance.py`](../../../tools/doc_scripts/doc_reliance.py)). Unmet is a `::warning::`, not a failure; `--strict` makes it one. Project size is only ever a warning. `related:` and prose links are never read as reliance.

`--fix` first cuts every superseded revision down to its frozen sections, then runs the checks:

```bash
cd tools && uv run python -m doc_scripts.check_doc_drift --fix
```

### Service records

A section that does not apply says so and why, and one not known yet says `Unknown:`; only an empty one fails. Other sections may sit between, and several apps may name one record. The check does not test that a section is true ([ADR 0100](../../decisions/0100-recording-how-a-system-is-integrated/revision-000.md), [`doc_records.py`](../../../tools/doc_scripts/doc_records.py)). The shape of `doc:` is [the catalog rules'](../engineering/ci/gates.md#app-catalog-rules).

## Moved-file check

[`check_moved_files.py`](../../../tools/doc_scripts/check_moved_files.py) takes every file `git log` shows was renamed or deleted and is no longer anywhere, and looks for those names in every tracked or new text file except `tools/tests/`. Left out: a name another tracked file still has, a name with no extension, and `conf.yaml` or `conf.yml`, which containers create at run time.

| Where the old name is | Result |
| :--- | :--- |
| Outside `docs/decisions/` | Fails, giving the new path or saying it was removed |
| In a decision revision | The name stays; its first mention needs `(renamed: new)`, `(removed)` or `(removed; replaced by: new)` after it. A link to the current file stands in, and a table row needs none ([editing a revision](../../decisions/README.md#editing-a-revision)) |

It checks the whole tree against the whole history on every run, so a reference that went stale is caught by the next run. CI fetches the history (`fetch-depth: 0`); in a shallow clone the check says so and passes.

## Retired-number check

[`tools/doc_scripts/check_retired_numbers.py`](../../../tools/doc_scripts/check_retired_numbers.py), a local pre-commit hook like the
drift check, so CI runs it in `pre-commit-checks`. A decision number is
retired when its lineage was merged into another (it is that lineage's
`former_ids`) or demoted or dropped (it is listed in
[`removed.md`](../../decisions/removed.md)). Nothing redirects it, and the
drift check reads link targets and `related:` entries, not text, so a stale
number written as text passed it. This reads every tracked or new text file,
code, workflows and config included, and fails on:

- `ADR NNNN` or `ADR-NNNN` for a retired number, and each number of a list or
  range after `ADRs` (`ADRs NNNN, NNNN and NNNN`, `ADRs NNNN through NNNN`);
- a link whose visible number is retired, bare (`[NNNN](...)`) or with a name,
  whatever it points to.

The error gives the line and the number to use, or says the record was
demoted or dropped. A bare number with no `ADR` before it is not read.

Left out: `removed.md`, a `former_ids` field, the `Formerly ADR-...` the
generated indexes print, the hyphenated id inside a markdown fence (a schema
example uses arbitrary ids), and `tools/tests/doc_scripts/`, whose fixtures
use arbitrary numbers.

A reference inside a frozen section of an `accepted` or `superseded` revision
(see the [accepted records check](project-checks.md#accepted-records-check)) is fixed like any
other, but the commit that fixes it carries an `Editorial-Fix: <path>` trailer
or the `project-checks` job fails the pull request. The error says so. The
hook cannot tell that the trailer is there, and does not need to: it fails
until the number is fixed.

It reads the working tree only, so it works in a shallow clone.

## Command-block check

[`tools/doc_scripts/check_command_blocks.py`](../../../tools/doc_scripts/check_command_blocks.py), a local pre-commit hook like the
drift check, so CI runs it in `pre-commit-checks`. It holds the fenced blocks
of every tracked or new markdown file outside `docs/decisions/` to the part of
[`AGENTS.md`](../../../AGENTS.md#command-blocks-for-the-operator) a script
can decide:

| Fails on | In |
| :--- | :--- |
| A fence that names no language | Every fence |
| A `<placeholder>`, a `{{ variable }}` or a bare `...` where a value goes | Shell fences (`sh`, `bash`, `shell`) |
| A second `# [n/m]` segment | Shell fences |
| A command that waits for input with a command after it | Shell fences |
| A literal value assigned to a secret-named variable, such as one ending `_TOKEN` | Shell fences |
| `curl -u` or `--user` | Shell fences |

Comments are not read, apart from the segment markers, and a `text` fence holds
a usage synopsis or output that nobody pastes. The commands it knows to wait
for input are `read`, `openbao_utils.shell` and `unseal`, an interactive `ssh`
or `sudo -i`, `gpg` key generation and `docker run -it`; a `read` fed by a pipe
or a redirection is not one. Whether a value is secret, where a file lands and a
password prompt of `sudo` or `ssh` are left to review. It reads the working tree
only, so it works in a shallow clone.

## Mermaid render check

The other checks read a diagram as text. [`check_mermaid.py`](../../../tools/doc_scripts/check_mermaid.py) renders every `mermaid` block of every tracked `.md` file, leaving out one quoted inside a longer fence ([ADR 0078 (Diagram render check)](../../decisions/0078-checking-that-diagrams-in-docs-render/revision-000.md)).

- **Renderer:** the pinned `mermaid-cli` image (`MERMAID_CLI_IMAGE` in the module), the block on stdin, no network, no capabilities. Renovate bumps the tag there, and the [image tag check](../engineering/ci/image-tag-check.md) reads it there.
- **CI:** the `mermaid-check` job, when a markdown file or the module changed. It checks every block, so an image bump is tried against every diagram. It uses the runner's `python3` and Docker, and is [required directly](../engineering/ci/pipeline.md#requiring-checks-before-merge).
- **No pre-commit hook:** `pre-commit-checks` runs every hook on every file, so one would pull the image and render every diagram on pull requests that touch no docs.

To check before pushing, with Docker available:

```bash
cd tools && python3 -m doc_scripts.check_mermaid
```

| Result | Meaning |
| :--- | :--- |
| exit 0 | every block renders; it may still read badly, and GitHub uses its own Mermaid version, so look at a changed diagram rendered |
| exit 1 | each failing block is listed with file, line and the renderer's first message |
| exit 2 | Docker could not run the image, so no block was judged |
