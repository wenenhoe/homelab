# Doc Checks

The hooks and jobs that keep the docs consistent with the files and config they describe: index generation, the drift check, the moved-file and retired-number checks, and the Mermaid render check. The checks on project and decision records are in [Project and Record Checks](project-checks.md). How they sit in the pipeline is in [CI: PR Checks](../engineering/ci/pipeline.md).

## Doc index generation

[`tools/doc_scripts/generate_doc_indexes.py`](../../../tools/doc_scripts/generate_doc_indexes.py),
wired into `.config/.pre-commit-config.yaml` as a local hook, positioned before
markdownlint/`check-doc-drift` below — it needs to run first so a bad
generation gets caught by the checks that follow, the same way a bad
hand-edit already is. Reads every `docs/projects/*.md` and every decision revision's
frontmatter and writes `docs/project-planning.md`'s Roadmap, Super Projects,
Projects, Decisions awaiting a project and Open explorations views, and
`docs/decision-index.md`'s By number, By topic, Open decisions and History
views, and the coverage table, each whole: the title and introduction come from its file in
[`tools/doc_scripts/view_intros/`](../../../tools/doc_scripts/view_intros), then the sections. None of the three is committed; they are
git-ignored, and the hook also runs after a checkout, a merge and a rebase so a clone has them. It validates each doc's frontmatter as it goes.
The Unblocks counts, the Status and Blocker cells, the order of the
project tables, and the approved-first order of the decisions table are computed from that
frontmatter alone, with nothing stored for them. The same holds for the
"Relies on" note a lineage carries in the decision index, with the target's
state, and the "rests on ADR-NNNN (state)" label a project shows in its
Blocker cell while its decision revision has an unmet `relies_on:`
([ADR 0082 (Choosing the next project)](../../decisions/0082-choosing-which-project-to-take-up-next/revision-002.md)). The Roadmap has a row per initiative, in the numbered list under `## Initiatives` in
[`docs/projects/README.md`](../../projects/README.md#initiatives), then a row for projects with no
`super_project`, and sorts each project into In progress (building or de-risking), Startable (not started
with a Blocker of `—`) or Waiting from the same Status and Blocker cells; a done project is not shown. The
generator fails, naming each, for a `super_project` missing from the list, an initiative listed twice and
an initiative that no project uses, and writes nothing. That list is the only stored order: it ranks
initiatives, and no project field holds one. Same
auto-fix pattern as the `ruff --fix` and `dclint-docker` hooks: a stale table
fails the commit and shows the regenerated diff, rather than silently
passing. It stops before writing anything when two lineage directories
share a number, naming both and pointing at the
[renumber helper](project-checks.md#renumbering-a-patch-series-lineages).

It also regenerates the `## Apps` table of
[`coverage.md`](https://wenenhoe.github.io/homelab/dr-coverage/) from the app catalog and the
inventory ([`doc_coverage.py`](../../../tools/doc_scripts/doc_coverage.py)): each
app's hosts, volumes, routes, backup, service record and recovery tier. It reads no
result of any exercise.

## Docs drift check

[`tools/doc_scripts/check_doc_drift.py`](../../../tools/doc_scripts/check_doc_drift.py), wired into
`.config/.pre-commit-config.yaml` as a local hook — no separate job of its own, it rides along inside
[`pre-commit-checks`](../engineering/ci/pipeline.md#jobs) like every other commit-stage hook. Checks
these narrow, structural things:

- Every doc directly under `docs/` is linked somewhere in
  `docs/README.md` (both directions — a link to a deleted file fails
  too). The same check applies one level down for `docs/decisions/`,
  `docs/architecture/`, and `docs/projects/`, each against its own
  `README.md` index, and at any depth under `docs/topics/` against
  `docs/topics/README.md`, where each doc is matched by its path
  relative to that index so same-named docs in different folders can't
  satisfy each other.
- `docs/topics/deploy/ansible.md`'s Playbooks and Roles tables list exactly the files
  under `ansible/playbooks/*.yaml` and directories under
  `ansible/roles/*/`.
- `docs/topics/testing/molecule-testing.md`'s Scenario matrix table lists exactly the
  scenario directories that exist under `ansible/roles/*/molecule/*/`.
- `docs/topics/deploy/deployment-flow.md`'s Plays table has one row per play in
  `deploy.yaml`, numbered sequentially from 0. Wording isn't compared, only
  count and sequence, so a row paraphrasing a play's name isn't flagged as drift.
- [`pipeline.md`](../engineering/ci/pipeline.md#jobs)'s Jobs table lists every `pr-checks.yml` job id, except
  `detect-changes` (internal plumbing) and `trivy-scan` (documented in
  [`security-scanning.md`](../security/policy/security-scanning.md) instead).
- Every `app_catalog` entry names its service record with `doc:`
  ([`doc_records.py`](../../../tools/doc_scripts/doc_records.py), [ADR 0100](../../decisions/0100-recording-how-a-system-is-integrated/revision-000.md)).
  The named doc must exist and have the seven `##` sections `Dependencies`, `Data`,
  `Exposure`, `Threat model`, `Observability`, `Disaster recovery` and `Lifecycle`,
  in that order (other sections may sit between them), each with something under it.
  A section that does not apply says so and why, and one not known yet says `Unknown:`;
  only an empty one fails. Several entries may name one record. It checks that the
  sections are present and filled, not that they are true. The value's shape is
  [the catalog rules'](../engineering/ci/gates.md#app-catalog-rules).
- Every cross-file `#anchor` reference anywhere in the repo (not just
  `.md` files — YAML/Python comments too) resolves to a real file with
  a heading that actually slugs to that anchor; same for same-file
  `#anchor` links. Catches the class of bug a file move/rename/split
  leaves behind.
- No markdown file links a generated view by its file path: the decision index, the planning view and the coverage table are linked through their pages on the site, and every link to the site, to a view's page or a document's, names a page that exists and, after a `#`, a heading, section or list of headings on it. The headings are those of the pages built from the tree ([`doc-site.md`](doc-site.md#linking-a-view)). The views link each other by path, and are not checked.
- Every path under `docs/decisions/` or `docs/projects/` ending in `.md`
  that is written in any docs, code, or config file (`.md`, `.py`,
  `.yaml`, `.sh`, `.toml`, …) exists — comments included. This is what
  catches a renamed ADR mentioned in a comment, which the anchor check
  can't see because such a path carries no `#anchor`, and it fails a
  comment that points at a project doc the day that project is deleted.
  A path containing `NNN` is a placeholder; a deleted file is referred to
  by name, not by path.
- Every ADR linked from
  [`nist-800-53-alignment.md`](../security/policy/nist-800-53-alignment.md) isn't
  `status: superseded` — the one state transition the anchor check
  above can't catch, since a superseded ADR's file doesn't move or
  break any link. Doesn't check whether an *accepted* ADR's reasoning
  drifted, or whether a new ADR should be added there — that's still
  on whoever's making the change, per that page's own notes.
- Decision lineages (`docs/decisions/NNNN-slug/revision-NNN.md`) follow
  [Lineages and revisions](../../decisions/README.md#lineages-and-revisions) and
  [Revision states](../../decisions/README.md#revision-states): generations and
  candidate letters with none missing, at most one `accepted` revision, and a
  `superseded` one that names its `accepted` successor, which declares `supersedes`
  back. `title`, `short` and `topic` are identical across a lineage's revisions, and
  `short` is unique across lineages (ignoring case); `narrows`, `related`, and
  `former_ids` reference real lineages, and a `former_ids` entry is never a live
  lineage. Each lineage directory is linked from `decision-index.md`. An `approved`
  or `accepted` revision has no open `Assumptions` entry
  ([the gate](../../decisions/README.md#assumptions)): the check sees a bullet, not
  whether the claim is genuinely resolved.
- A decision revision's heading and state: an unlettered revision 0 opens with
  `# NNNN. <title>`, and no revision carries a `**Status:**` body line.
- A markdown link written `[ADR 0044 (CD agent trigger)]`, or with a
  revision after the number, carries that lineage's `short:` name
  exactly, so renaming a lineage can't leave links using the old name.
  A link with only the number is not checked: the name is never
  required. See
  [`docs/decisions/README.md#citing-a-decision`](../../decisions/README.md#citing-a-decision).
- A project's `decision:` revision is in the state its status requires, and its
  status agrees with its stage table ([Lifecycle](../../projects/README.md#lifecycle)).
  Projects without a `decision:` are never gated. `depends_on` entries name existing
  project docs, never themselves, and form no cycle.
- A stage that is not a build change fails unless it is `Done`
  ([What a stage is](../../projects/README.md#what-a-stage-is),
  [ADR 0037 revision 5](../../decisions/0037-decision-and-project-documentation-workflow/revision-005.md)).
  The patterns are `STAGE_KINDS` in `doc_scope.py`. A finished one stays as history.
- A project whose `decision:` revision is `working` carries `plan: draft`.
- A `superseded` revision keeps only its frozen sections, and any other `##` section
  fails, naming it. `check_doc_drift --fix` cuts the revision to them first, then runs
  the checks ([Superseded revisions](../../decisions/README.md#superseded-revisions)).
- A revision's `weight` is `full` or `light`; a `light` one has no forbidden section
  and a body of at most `LIGHT_MAX_WORDS` words (`doc_graph.py`)
  ([Weights](../../decisions/README.md#weights)).
- Explorations (`docs/explorations/<slug>.md`): the frontmatter has
  `type: exploration`, `status: open`, a `topic`, and an `id` of `EXP-` plus
  the file name; `related` entries name real lineages. No file outside
  `docs/explorations/` names an exploration, by its path from the repository root or by a
  link relative to the file, apart from the generated `project-planning.md`, since an
  exploration is deleted when it ends. See
  [`docs/explorations/README.md`](../../explorations/README.md).
- No doc or comment outside `docs/projects/`, `docs/decisions/` and `docs/explorations/` names
  a project's stage, phase or track ([`doc_stage_words.py`](../../../tools/doc_scripts/doc_stage_words.py)).
  A stage word alone is allowed, since a playbook has stages of its own; the check fires when
  one paragraph, list item or table row also links a project doc or names a `PROJ-` id.
  `AGENTS.md` gives the reason: the vocabulary is deleted with the project.
- The zone policy in [`opnsense-gateway.md`](../infra/tofu/opnsense-gateway.md#zone-policy)
  names each flow in the first cell of its row, as a code span of lowercase words joined by hyphens, and
  uses no name twice ([`doc_policy_flows.py`](../../../tools/doc_scripts/doc_policy_flows.py)). A link
  to that section whose text is such a name must name a flow in the table, and a doc that links the
  gateway doc, or is it, does not cite a row by its number (the word `row` or `rows` followed by one). A number changes
  when a row is added or moved, a name does not. The decisions are frozen and keep the numbers they have.
- Relative links (`./`, `../`) from a `.md` file to a config, script, or
  data file (`.yaml`, `.hcl`, `.py`, …) resolve to a real file, the same
  way `.md` links do.
- A declared reliance (`relies_on:` in a decision revision) is met. An
  `approved` revision needs a revision of the target lineage that is
  `approved` or `accepted`, and an `accepted` one needs one that is
  `accepted`; a revision in any other state is not checked. An unmet one is
  printed as a `::warning::` naming the reliant revision, the target, its
  state and the reason, and does not change the exit status. `--strict`
  makes each a failure, for CI once the warnings are settled. Only declared
  reliance is read, never `related:` or links in prose. The `doc_reliance.py`
  module holds the rule; see
  [`docs/decisions/README.md#relying-on-another-lineage`](../../decisions/README.md#relying-on-another-lineage).

Deliberately presence/shape checks, not content review — it can't tell
you a description is *wrong*, only that something's missing or a
documented thing no longer exists.

## Moved-file check

[`tools/doc_scripts/check_moved_files.py`](../../../tools/doc_scripts/check_moved_files.py), a local pre-commit hook like the
drift check. It takes every file that `git log` shows was renamed or deleted
and is no longer anywhere in the tree (a name another tracked file still
has, a name with no extension, and `conf.yaml`/`conf.yml`, which containers
create at run time, are left out), then looks for those names in every
tracked or new text file except `tools/tests/`.

- Outside `docs/decisions/`, any mention fails, and the error gives the
  path the file moved to, or says it was removed.
- In a decision revision the old name stays, and its first mention needs a
  note after it: `old (renamed: new)`, `old (removed)` or
  `old (removed; replaced by: new)`. A link to the file as it is now stands
  in for the note, and a table row needs none. The rule is in
  [`docs/decisions/README.md#editing-a-revision`](../../decisions/README.md#editing-a-revision).

It checks the whole tree against the whole history on every run, not only
the files a change touches, so a reference that went stale outside a PR is
caught by the next one and no scheduled sweep is needed. That needs history:
`pre-commit-checks` fetches it (`fetch-depth: 0`), and in a shallow clone
the check says so and passes, so a local `--depth` clone is not blocked.

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

## Mermaid render check

[`tools/doc_scripts/check_mermaid.py`](../../../tools/doc_scripts/check_mermaid.py) renders
every Mermaid diagram in the repo's markdown, which none of the checks above does: they read
a diagram as text, so a block that does not render passes them all
([ADR 0078 (Diagram render check)](../../decisions/0078-checking-that-diagrams-in-docs-render/revision-000.md)).
It finds each fenced `mermaid` block in the tracked `.md` files, leaving out one quoted inside a
longer fence, and runs the pinned `mermaid-cli` container image on it: the block on stdin, no
network, no capabilities. The image tag is the module's `MERMAID_CLI_IMAGE`; Renovate bumps it
there, and the [weekly image tag check](../engineering/ci/image-tag-check.md) reads it there.

It runs in CI only, as the `mermaid-check` job, when `detect-changes` reports a markdown file or
the module itself changed. It checks every block in the repo, not only the changed ones, so a bump
of the image is tried against every existing diagram. It runs on the runner's own `python3` and
Docker, and it is not a matrix job, so it can be required directly (see
[Requiring checks before merge](../engineering/ci/pipeline.md#requiring-checks-before-merge)).

There is no pre-commit hook for it: `pre-commit-checks` runs every hook over every file on every
PR, so a hook would pull the image and start a browser per diagram on PRs that touch no docs. To
check before pushing, run `python3 -m doc_scripts.check_mermaid` from `tools/`; it needs Docker and
nothing else.

For every block that does not render, it prints the file, the line the block starts on and the
renderer's first error message, not only the first failure. Exit status 2, not 1, means Docker
could not run the image, so no block was judged. A pass shows that a block renders, not that it
reads well, and GitHub draws with its own Mermaid version, so a new or changed diagram still gets a
look in a rendered view.
