# CI Doc Checks

The hooks and jobs that keep docs and project records consistent: index generation, the drift check, the project scope, close, start and accepted-records checks, the one command that runs them, and the Mermaid render check, plus the helpers that suggest a project's scope and renumber the lineages a patch series adds. How they sit in the pipeline is in [CI: PR Checks](pipeline.md).

## Doc index generation

[`tools/doc_scripts/generate_doc_indexes.py`](../../../../tools/doc_scripts/generate_doc_indexes.py),
wired into `.config/.pre-commit-config.yaml` as a local hook, positioned before
markdownlint/`check-doc-drift` below — it needs to run first so a bad
generation gets caught by the checks that follow, the same way a bad
hand-edit already is. Reads every `docs/projects/*.md` and every decision revision's
frontmatter and regenerates `docs/project-planning.md`'s Super Projects,
Projects, Decisions awaiting a project and Open explorations views, and
`docs/decision-index.md`'s By number, By topic, Open decisions and History
views in place, validating each doc's frontmatter as it goes.
The Unblocks counts, the Status and Blocker cells, the order of the
project tables, and the approved-first order of the decisions table are computed from that
frontmatter alone, with nothing stored for them. The same holds for the
"Relies on" note a lineage carries in the decision index, with the target's
state, and the "rests on ADR-NNNN (state)" label a project shows in its
Blocker cell while its decision revision has an unmet `relies_on:`
([ADR 0082 (Choosing the next project)](../../../decisions/0082-choosing-which-project-to-take-up-next/revision-000.md)). Same
auto-fix pattern as the `ruff --fix` and `dclint-docker` hooks: a stale table
fails the commit and shows the regenerated diff, rather than silently
passing. It stops before writing anything when two lineage directories
share a number, naming both and pointing at the
[renumber helper](#renumbering-a-patch-series-lineages).

It also regenerates the `## Apps` table of
[`coverage.md`](../../disaster-recovery/coverage.md) from the app catalog, the
inventory and the fire-drill results table
([`doc_coverage.py`](../../../../tools/doc_scripts/doc_coverage.py)). Each item
in the fire-drill table's "Apps covered" column must be a catalog app key (any
case, with an optional parenthetical) or `None`; any other name stops the
generation and is reported.

## Docs drift check

[`tools/doc_scripts/check_doc_drift.py`](../../../../tools/doc_scripts/check_doc_drift.py), wired into
`.config/.pre-commit-config.yaml` as a local hook — no separate job of its own, it rides along inside
[`pre-commit-checks`](pipeline.md#jobs) like every other commit-stage hook. Checks
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
- `docs/topics/engineering/molecule-testing.md`'s Scenario matrix table lists exactly the
  scenario directories that exist under `ansible/roles/*/molecule/*/`.
- `docs/topics/deploy/deployment-flow.md`'s Plays table has one row per play in
  `deploy.yaml`, numbered sequentially from 0. Wording isn't compared, only
  count and sequence, so a row paraphrasing a play's name isn't flagged as drift.
- [`pipeline.md`](pipeline.md#jobs)'s Jobs table lists every `pr-checks.yml` job id, except
  `detect-changes` (internal plumbing) and `trivy-scan` (documented in
  [`security-scanning.md`](../security-scanning.md) instead).
- Every `app_catalog` entry names its service record with `doc:`
  ([`doc_records.py`](../../../../tools/doc_scripts/doc_records.py), [ADR 0100](../../../decisions/0100-recording-how-a-system-is-integrated/revision-000.md)).
  The named doc must exist and have the seven `##` sections `Dependencies`, `Data`,
  `Exposure`, `Threat model`, `Observability`, `Disaster recovery` and `Lifecycle`,
  in that order (other sections may sit between them), each with something under it.
  A section that does not apply says so and why, and one not known yet says `Unknown:`;
  only an empty one fails. Several entries may name one record. It checks that the
  sections are present and filled, not that they are true. The value's shape is
  [the catalog rules'](gates.md#app-catalog-rules).
- Every cross-file `#anchor` reference anywhere in the repo (not just
  `.md` files — YAML/Python comments too) resolves to a real file with
  a heading that actually slugs to that anchor; same for same-file
  `#anchor` links. Catches the class of bug a file move/rename/split
  leaves behind.
- Every path under `docs/decisions/` or `docs/projects/` ending in `.md`
  that is written in any docs, code, or config file (`.md`, `.py`,
  `.yaml`, `.sh`, `.toml`, …) exists — comments included. This is what
  catches a renamed ADR mentioned in a comment, which the anchor check
  can't see because such a path carries no `#anchor`, and it fails a
  comment that points at a project doc the day that project is deleted.
  A path containing `NNN` is a placeholder; a deleted file is referred to
  by name, not by path.
- Every ADR linked from
  [`nist-800-53-alignment.md`](../nist-800-53-alignment.md) isn't
  `status: superseded` — the one state transition the anchor check
  above can't catch, since a superseded ADR's file doesn't move or
  break any link. Doesn't check whether an *accepted* ADR's reasoning
  drifted, or whether a new ADR should be added there — that's still
  on whoever's making the change, per that page's own notes.
- Decision lineages (`docs/decisions/NNNN-slug/revision-NNN.md`):
  generations (`revision-NNN`) run 000..NNN with no gaps; competing
  candidates in one generation are lettered a, b, c… with none missing,
  and once one is `approved` or beyond the rest are `abandoned`; at most one revision is
  `accepted`; a `superseded` revision names a later `accepted` (or
  itself superseded) successor that declares `supersedes` back;
  `title`, `short` and `topic` are identical across a lineage's revisions,
  and `short` is unique across lineages (ignoring case);
  `narrows`, `related`, and `former_ids` reference real lineages, and a
  `former_ids` entry is never a live lineage. Each lineage directory is
  linked from `decision-index.md`. An `approved` or `accepted`
  revision has no open `Assumptions` entry — the hard gate in
  [`docs/decisions/README.md#assumptions`](../../../decisions/README.md#assumptions).
  Presence-of-a-bullet only, not whether the claim is genuinely
  resolved; that judgment call is still on whoever sets the status.
- A decision revision's heading and state: an unlettered revision 0
  opens with `# NNNN. <title>` (its lineage number and `title:`), and
  no revision carries a `**Status:**` body line, since the frontmatter
  `status` is the one record. Later and lettered revisions name their
  own solution in their heading, so only revision 0 is checked.
- A markdown link written `[ADR 0044 (CD agent trigger)]`, or with a
  revision after the number, carries that lineage's `short:` name
  exactly, so renaming a lineage can't leave links using the old name.
  A link with only the number is not checked: the name is never
  required. See
  [`docs/decisions/README.md#citing-a-decision`](../../../decisions/README.md#citing-a-decision).
- A project's `decision:` revision must be in the state its status
  requires: `not-started` → `working` or `approved`, `de-risking` →
  `working`, `building` → `approved`, `done` → `accepted`. A revision
  dropping back to `working` therefore fails the check for any project
  that is `building` on it. Projects without a `decision:` are never
  gated. `depends_on` entries name existing project docs, never
  themselves, and form no cycle.
- A project's status must agree with its stage table: `not-started` fails with
  a stage `In progress` or `Done`, and `de-risking` or `building` fails with
  every stage `Not started`. A doc with no stage rows is not judged.
- A stage named `Spike` or `Spikes` that is not `Done` fails when the project's
  `decision:` revision is `approved` or `accepted`: the revision was approved
  before the assumption was resolved, or the spike is build work under another
  name. A finished spike stays as history.
- A `superseded` revision keeps only the frozen sections (Problem, Decision,
  Invariants, Non-goals, Reconsideration triggers): any other `##` section
  fails, naming it. `check_doc_drift --fix` cuts the revision to those
  sections first and then runs the checks; the cut cannot change a frozen
  section, so the accepted-records check sees no change. See
  [`docs/decisions/README.md#superseded-revisions`](../../../decisions/README.md#superseded-revisions).
- A revision's `weight` is `full` or `light`. A `light` revision has no
  `Invariants`, `Non-goals` or `Validation` section and a body of at most
  `LIGHT_MAX_WORDS` words (`doc_graph.py`); a full one is not limited. See
  [`docs/decisions/README.md#weights`](../../../decisions/README.md#weights).
- Explorations (`docs/explorations/<slug>.md`): the frontmatter has
  `type: exploration`, `status: open`, a `topic`, and an `id` of `EXP-` plus
  the file name; `related` entries name real lineages. No file outside
  `docs/explorations/` names an exploration's path, apart from the generated
  `project-planning.md`, since an exploration is deleted when it ends. See
  [`docs/explorations/README.md`](../../../explorations/README.md). The
  generator also warns about an open exploration whose newest commit is older
  than `EXPLORATION_STALE_DAYS` in `doc_explorations.py`; a warning never fails.
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
  [`docs/decisions/README.md#relying-on-another-lineage`](../../../decisions/README.md#relying-on-another-lineage).

Deliberately presence/shape checks, not content review — it can't tell
you a description is *wrong*, only that something's missing or a
documented thing no longer exists.

## Project scope check

[`tools/doc_scripts/check_project_scope.py`](../../../../tools/doc_scripts/check_project_scope.py) enforces the optional
`allowed_paths` field on project docs (see
[`docs/projects/README.md#scope`](../../../projects/README.md#scope) for what it means
and why). It runs in two places:

- **CI** — the scope step of the `project-checks` job, on every pull request: the diff from
  the merge-base of the PR's base and head to its head. The merge-base,
  not the base tip, so a branch that is behind doesn't see main's newer
  commits as its own changes. The repo's other diff-based jobs diff
  `$BASE $HEAD` directly; this one deliberately doesn't.
- **pre-commit** — the `check-doc-change` hook, on what is staged,
  against `HEAD`. It sees only the current commit, so it is early
  feedback; CI is the authority, since it sees the whole PR. Under
  `pre-commit-checks`' `--all-files` run nothing is staged and it passes
  trivially.

In both, a project's scope is read from the doc **as it stands on the
base**, so a change can't widen its own scope and then use it. The
decision revisions a project's close edits need no entry: the one
`decision:` names, each one in `also_implements:`, and the revision each
supersedes. They come from the base project doc and from the `supersedes:`
the base revision has, never from the change, so a change can't add one
([`doc_scope.lifecycle_paths`](../../../../tools/doc_scripts/doc_scope.py)). A project
binds a change only if the change *works* its doc: its frontmatter or a
stage's number or status in the Execution plan table differs from the base,
or the doc is deleted. A prose or link edit to the doc, such as a sweep
across every project doc, binds nothing, so a repo-wide docs cleanup
isn't held to the scope of whichever projects it happened to edit. A project
doc that is new in the change has no scope yet. Renames and deletions
count as touching both paths. Path-level only: it can't tell whether an
edit inside an allowed file is the permitted one, and a change that never
works its project doc isn't bounded.

## Scope suggestions

[`tools/doc_scripts/suggest_project_scope.py`](../../../../tools/doc_scripts/suggest_project_scope.py)
is a helper, not a check: no hook or job runs it, and it always exits 0. Run it
from `tools/` when writing or revising a project's `allowed_paths`:

```text
python3 -m doc_scripts.suggest_project_scope NAME [--sweep TERM ...]
```

`NAME` is the project doc's file name, with or without `.md`, or its path from
the repository root. It reads the doc and the tree as they stand now, not the
base, and prints
four lists. Each holds only files the scope doesn't cover yet, and `none`
means that pass found nothing.

- **Exempt without an entry** — the decision revisions the close edits (see
  [Project scope check](#project-scope-check)).
- **Named by the project doc** — tracked files named by a code-span path or a
  relative link in the doc's Scope (without its `Not in` paragraph), Execution
  plan and Acceptance criteria. A named directory becomes a `dir/**` entry. A
  path no tracked file matches, such as a file the project will create, isn't
  found.
- **Edited by the closing PR** — every file that names the project doc, since
  the drift check fails a path to a project doc that no longer exists, and
  the NIST alignment page when it links a revision the close supersedes.
- **Mentions of each `--sweep TERM`** — tracked files outside `docs/decisions/`
  that mention a name the project removes, renames or reshapes (fixed text,
  ignoring case), with the number of matching lines. Each is the author's call:
  put it in scope or name it under `Not in`. They stay out of the proposed block.

It ends with the `allowed_paths` block that adds the named and closing entries
to today's, leaving out an entry another new entry already covers. A new topic
doc's row in `docs/topics/README.md` isn't found, and no scope exempts that
file.

## Renumbering a patch series' lineages

[`tools/doc_scripts/renumber_adr_patches.py`](../../../../tools/doc_scripts/renumber_adr_patches.py)
is a helper, not a check: no hook or job runs it. Two patch series written
against the same `main` can each add a lineage with the same number. The
directories carry different slugs, so both apply and only the drift check
and the index generation notice. It reads each file as text, so it takes a
`.series` file as well as patches. Run it from `tools/` on the series, after
`git am --abort` if one is in progress:

```text
python3 -m doc_scripts.renumber_adr_patches PATCH... [--check] [--out DIR]
```

For each lineage the series adds whose number the tree holds under another
directory, it takes the next number that neither the tree nor the series
uses. It writes every patch to `renumbered/` beside the first patch, or to
`--out`, with that number replaced in the lineage's directory name, its
`ADR-NNNN` and `ADR NNNN` references, its `# NNNN.` heading and its index
link text. Any other text that contains the number is left as written, and
the originals are not modified. It prints each renumbering and the number of
replacements in each patch. `--check` prints the collisions and exits 1
without writing anything.

## Project close check

[`tools/doc_scripts/check_project_close.py`](../../../../tools/doc_scripts/check_project_close.py) enforces the closing rule in
[ADR 0037 revision 3 (Decision and project workflow)](../../../decisions/0037-decision-and-project-documentation-workflow/revision-003.md):
deleting a finished project's doc must not leave a revision it names
unaccepted with no project naming it. A deleted doc passes when each
revision it named on the base, in `decision:` or `also_implements:`, is
`accepted` afterwards, or another project doc that remains names it in
either field (`also_implements:` still gates no project's status). So the
last project to close either accepts the revision or leaves a
`not-started` successor naming it for whatever is unfinished. A doc that
names only `working` revisions is withdrawn rather than closed and may be
deleted: it has built nothing, and the revision shows in
[Decisions awaiting a project](../../../project-planning.md#decisions-awaiting-a-project).
A change that deletes no project doc isn't checked.

It runs in the same two places as the scope check, with the same
merge-base diff and the same staged-changes behavior:

- **CI** — the close step of the `project-checks` job, on every pull request, judging the
  PR's head.
- **pre-commit** — the `check-doc-change` hook, judging the index
  against `HEAD`. It is early feedback; CI is the authority. Under
  `pre-commit-checks`' `--all-files` run nothing is staged and it passes
  trivially.

Unlike the scope check, it reads the docs as they stand **after** the
change, since it has to see what the change leaves behind; the base
supplies only the deleted doc's own `decision:`. A doc that doesn't parse
after the change fails the check rather than being skipped, and
`check_doc_drift.py` names it. A rename counts as a deletion plus an
addition, so a renamed project doc keeps its revision named.

Two PRs that each leave the other's project in place can both pass and
together leave a revision `approved` with no project. The generated
[Decisions awaiting a project](../../../project-planning.md#decisions-awaiting-a-project)
view lists it, so the gap is visible but not blocked.

## Project start check

[`tools/doc_scripts/check_project_start.py`](../../../../tools/doc_scripts/check_project_start.py) enforces the start rule in
[ADR 0037 revision 4 (Decision and project workflow)](../../../decisions/0037-decision-and-project-documentation-workflow/revision-004.md):
a project doc that a change adds is `not-started` only when its `decision:`
revision is `approved`, or it names none. A project on a `working` revision
starts as `de-risking`, limited to spikes and reading code. The rule reads
only the docs the change adds (a rename counts as one), so a project that was
already waiting on a `working` revision is not re-judged.

It runs where the close check runs, with the same merge-base diff and the same
staged-changes behavior: the `project-checks` job in CI, and the
`check-doc-change` hook on the index, which passes trivially under
`--all-files`. It reads the docs as they stand after the change, and a doc that
does not parse fails the check.

The generator also warns, without failing, when more than
`ACTIVE_PROJECT_LIMIT` projects (`generate_doc_indexes.py`) are `building` or
`de-risking` at once.

## Accepted records check

[`tools/doc_scripts/check_accepted_records.py`](../../../../tools/doc_scripts/check_accepted_records.py) holds the rules for
compacting accepted decisions in
[ADR 0037 revision 4 (Decision and project workflow)](../../../decisions/0037-decision-and-project-documentation-workflow/revision-004.md),
described for the maintainer in
[`docs/decisions/README.md#compacting-accepted-records`](../../../decisions/README.md#compacting-accepted-records).
It enforces two rules:

- **Frozen sections.** A revision that was `accepted` or `superseded` on the
  base keeps its `title`, its `solution`, and its Problem, Decision,
  Invariants, Non-goals and Reconsideration triggers sections. Link targets,
  moved-file notes and short names in link text are ignored, and whitespace is
  collapsed, so the editorial edits the decisions README allows are not
  changes. A commit of the pull request with an `Editorial-Fix: <path>` trailer
  excuses that file.
- **Removed lineages.** A lineage that held an `accepted` or `superseded`
  revision on the base and is gone afterwards must be a `former_ids` entry of
  a lineage that remains, or be listed in
  [`removed.md`](../../../decisions/removed.md). The drift check also fails a
  number listed there that a lineage holds, or that is a former id too.

It runs in the same two places as the other project-checks: the
`project-checks` job over the pull request, which fails on both rules, and the
`check-doc-change` hook on the index, which reports a changed frozen
section as a warning only (the trailer that excuses it is written with the
commit message, after the hook runs) and still fails on a lineage that leaves
unaccounted for. It reads the docs as they stand after the change for the
removal rule, and a doc that does not parse fails the check.

## The four project and record checks as one command

[`tools/doc_scripts/check_doc_change.py`](../../../../tools/doc_scripts/check_doc_change.py)
runs the project scope, close and start checks and the accepted records check
above, in that order and all of them even if one fails. Each check is still its
own module with its own tests; this is the one entry point the hooks and CI
call, so a rule added to the list runs everywhere at once. It has three forms:

- **`--staged`**, the `check-doc-change` hook at commit time. It sees one
  commit, so a stray file in an earlier commit of the branch passes it, and the
  accepted records check can only warn about a frozen section because the
  `Editorial-Fix:` trailer is written after the hook runs.
- **`--base REF --head REF`**, the one step of the `project-checks` job, over
  the whole pull request.
- **`--push`**, the `check-doc-change-push` hook at the `pre-push` stage, the
  `--base` form over the commits being pushed against the default branch, so
  what the staged form cannot see shows before CI.

For `--push`:

- **The base** is the remote's HEAD (`origin/HEAD`), else `origin/main`,
  `origin/master`, `main` or `master`. It is not fetched: the checks read the
  merge-base, so a stale base still gives the branch's own commits.
- **The head** is the commit being pushed (`PRE_COMMIT_TO_REF`), else `HEAD`.
- **Skipped**, with a message and a pass, when there is no default branch in the
  clone, when the head shares no history with it (a shallow clone), when the
  push adds no commit, or when it deletes a ref. The `ansible-lint` job runs
  every push-stage hook against all files in a shallow checkout, so this
  skips there; the `project-checks` job is where the pull request is judged.

The error output is each check's own, followed by the names of the checks that
failed.

## Merge preparation

[`tools/doc_scripts/merge_adr_links.py`](../../../../tools/doc_scripts/merge_adr_links.py)
runs nowhere in CI and is never run by an agent working a project: merging
decision records is the maintainer's operation
([ADR 0037 revision 4](../../../decisions/0037-decision-and-project-documentation-workflow/revision-004.md)),
and this only prepares the inbound side of one. The maintainer writes the new
lineage first, listing every source's id in its `former_ids`; then
`python3 -m doc_scripts.merge_adr_links NEW SOURCE [SOURCE ...]` (`--dry-run` to
read the report first) rewrites, in every tracked or new text file except the
sources, the new lineage and the generated views:

- a link to any revision of a source, which now goes to the new lineage's
  revision 0;
- `ADR NNNN` and `ADR-NNNN` for a source number, in prose, comments and link
  text, and the short name in a link to the new lineage;
- `ADR-NNNN/LABEL` in a project's `decision:` and `also_implements:`, which now
  name revision 0 of the new lineage;
- `related:` and `narrows:` of other records, with each id once.

It does not delete the sources, regenerate the views or commit. It prints what
is left for a person, which is what used to be found late:

- the revisions whose frozen sections changed, as `Editorial-Fix: <path>` lines
  to put on a commit of the change, since the accepted-records check fails the
  pull request without them;
- the project docs whose frontmatter or stage table changed, which makes the
  change work that project, so every changed file must be inside its
  `allowed_paths` on the base branch (widen them in an earlier change);
- lists and ranges (`ADRs A through B`) where a number was replaced, which can
  now read wrong;
- references left in the new lineage, which is never edited, and any other
  mention of a source directory.

Once the source directories are deleted and the views regenerated, the
[retired-number check](#retired-number-check) passes. The scan it shares with
this tool is `doc_retired.py`.

## Consolidation suggestions

[`tools/doc_scripts/suggest_adr_consolidation.py`](../../../../tools/doc_scripts/suggest_adr_consolidation.py)
runs nowhere in CI and changes nothing. It lists decisions that read like
implementation detail (an accepted Decision that names many files), lineages
whose title, summary and Problem share many words, and clusters of three or
more lineages of one topic that all list one another in `related:`. With
`--report` it adds whether too many projects are active. The limits are constants at the top of the script. What a hit means
is the maintainer's call.

A pair or cluster the maintainer has read and kept apart is recorded in the
decisions README's table
[Records the report lists that stay separate](../../../decisions/README.md#records-the-report-lists-that-stay-separate),
with a reason and, in its last column, each record's status when the row was
written (the status of its newest revision, so a pending `working` revision
counts). The report leaves a similar pair or tight cluster out when a row
covers it and none of its records has changed status. A row with a record that
changed status, is gone, or has no status recorded is listed under "Kept apart,
to read again" with the reason on file, whether or not the pair would be
reported now; a row the report cannot read is listed there too. Updating the
column is how a row is marked read again.

## Moved-file check

[`tools/doc_scripts/check_moved_files.py`](../../../../tools/doc_scripts/check_moved_files.py), a local pre-commit hook like the
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
  [`docs/decisions/README.md#editing-a-revision`](../../../decisions/README.md#editing-a-revision).

It checks the whole tree against the whole history on every run, not only
the files a change touches, so a reference that went stale outside a PR is
caught by the next one and no scheduled sweep is needed. That needs history:
`pre-commit-checks` fetches it (`fetch-depth: 0`), and in a shallow clone
the check says so and passes, so a local `--depth` clone is not blocked.

## Retired-number check

[`tools/doc_scripts/check_retired_numbers.py`](../../../../tools/doc_scripts/check_retired_numbers.py), a local pre-commit hook like the
drift check, so CI runs it in `pre-commit-checks`. A decision number is
retired when its lineage was merged into another (it is that lineage's
`former_ids`) or demoted or dropped (it is listed in
[`removed.md`](../../../decisions/removed.md)). Nothing redirects it, and the
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
(see the [accepted records check](#accepted-records-check)) is fixed like any
other, but the commit that fixes it carries an `Editorial-Fix: <path>` trailer
or the `project-checks` job fails the pull request. The error says so. The
hook cannot tell that the trailer is there, and does not need to: it fails
until the number is fixed.

It reads the working tree only, so it works in a shallow clone.

## Mermaid render check

[`tools/doc_scripts/check_mermaid.py`](../../../../tools/doc_scripts/check_mermaid.py) renders
every Mermaid diagram in the repo's markdown, which none of the checks above does: they read
a diagram as text, so a block that does not render passes them all
([ADR 0078 (Diagram render check)](../../../decisions/0078-checking-that-diagrams-in-docs-render/revision-000.md)).
It finds each fenced `mermaid` block in the tracked `.md` files, leaving out one quoted inside a
longer fence, and runs the pinned `mermaid-cli` container image on it: the block on stdin, no
network, no capabilities. The image tag is the module's `MERMAID_CLI_IMAGE`; Renovate bumps it
there, and the [weekly image tag check](image-tag-check.md) reads it there.

It runs in CI only, as the `mermaid-check` job, when `detect-changes` reports a markdown file or
the module itself changed. It checks every block in the repo, not only the changed ones, so a bump
of the image is tried against every existing diagram. It runs on the runner's own `python3` and
Docker, and it is not a matrix job, so it can be required directly (see
[Requiring checks before merge](pipeline.md#requiring-checks-before-merge)).

There is no pre-commit hook for it: `pre-commit-checks` runs every hook over every file on every
PR, so a hook would pull the image and start a browser per diagram on PRs that touch no docs. To
check before pushing, run `python3 -m doc_scripts.check_mermaid` from `tools/`; it needs Docker and
nothing else.

For every block that does not render, it prints the file, the line the block starts on and the
renderer's first error message, not only the first failure. Exit status 2, not 1, means Docker
could not run the image, so no block was judged. A pass shows that a block renders, not that it
reads well, and GitHub draws with its own Mermaid version, so a new or changed diagram still gets a
look in a rendered view.
