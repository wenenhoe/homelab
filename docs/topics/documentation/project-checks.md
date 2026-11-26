# Project and Record Checks

The hooks and jobs that keep project and decision records consistent: the project scope, size, close and start checks, the accepted-records check, the one command that runs them, the merge preparation that renumbers a patch series' lineages, and the helpers that suggest a project's scope and decision consolidations. The doc index, the drift check and the Mermaid render check are in [Doc Checks](doc-checks.md). How these sit in the pipeline is in [CI: PR Checks](../engineering/ci/pipeline.md).

## The four project and record checks as one command

[`tools/doc_scripts/check_doc_change.py`](../../../tools/doc_scripts/check_doc_change.py) runs the
[scope](#project-scope-check), [close](#project-close-check), [start](#project-start-check) and
[accepted records](#accepted-records-check) checks, in that order and all of them even if one fails.
Each is its own module with its own tests; this is the one entry point, so a rule added to the list
runs everywhere. Failed check names follow each check's own output.

| Form | Called by | Judges | Limits |
| :--- | :--- | :--- | :--- |
| `--staged` | `check-doc-change` hook, at commit | The index against `HEAD`. Passes trivially under `--all-files`, where nothing is staged. | One commit, so a stray file earlier on the branch passes. The start check can't judge the `Plan-Confirmed:` trailer, and a changed frozen section only warns, since trailers are written after the hook. |
| `--base REF --head REF` | `project-checks` job, on every pull request | The merge-base of the two to the head. | The authority. |
| `--push` | `check-doc-change-push` hook, at `pre-push` | The commits being pushed against the default branch. | Skips in some clones (below). |

The diff starts at the merge-base, not the base tip, so a branch behind `main` doesn't see newer
commits as its own. The repo's other diff-based jobs diff `$BASE $HEAD` directly.

To run what CI will judge, before pushing:

```sh
# from tools/
uv run python -m doc_scripts.check_doc_change --push
```

For `--push`:

- **The base** is `CHECK_DOC_CHANGE_BASE` when set (the landing tool sets it to the state before each
  pull request of a series), else `origin/HEAD`, else `origin/main`, `origin/master`, `main` or
  `master`. A name that is not a commit in the clone fails. The default branch is not fetched: a stale
  base still gives the branch's own commits.
- **The head** is the commit being pushed (`PRE_COMMIT_TO_REF`), else `HEAD`.
- **Skipped**, with a message and a pass, when the clone has no default branch, the head shares no
  history with it (a shallow clone, as in the `ansible-lint` job, which runs every push-stage hook),
  the push adds no commit, or it deletes a ref.

## Project scope check

[`tools/doc_scripts/check_project_scope.py`](../../../tools/doc_scripts/check_project_scope.py) enforces
the optional `allowed_paths` field on project docs
([`docs/projects/README.md#scope`](../../projects/README.md#scope) says what it means). The scope in
force, the decision revisions a close edits and what ties a change to a project are that page's rules.
The exempt revisions come from the base project doc and its `supersedes:`, never from the change
([`doc_scope.lifecycle_paths`](../../../tools/doc_scripts/doc_scope.py)). A rename or a deletion counts
as touching both paths.

## Project size warnings

[`tools/doc_scripts/doc_sizing.py`](../../../tools/doc_scripts/doc_sizing.py)
holds the size rules of [ADR 0037 revision 5](../../decisions/0037-decision-and-project-documentation-workflow/revision-005.md),
and [`docs/projects/README.md#sizing-a-project`](../../projects/README.md#sizing-a-project)
lists what each warns about. None fails a check. `check_doc_drift.py` prints them as
`::warning::`, and only when it has no errors. The [project start check](#project-start-check)
warns when a stage is added to a project that was already building.

## Scope suggestions

[`tools/doc_scripts/suggest_project_scope.py`](../../../tools/doc_scripts/suggest_project_scope.py)
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
  [Project scope check](#project-scope-check)). The other files the close
  edits, those naming the project doc, the NIST page and the topics index, are
  exempt in the check and aren't listed.
- **Named by the project doc** — tracked files named by a code-span path or a
  relative link in the doc's Scope (without its `Not in` paragraph), Execution
  plan and Acceptance criteria. A named directory becomes a `dir/**` entry. A
  path no tracked file matches, such as a file the project will create, isn't
  found.
- **Mentions of each `--sweep TERM`**, plus the doc's `sweep_terms` — tracked files outside `docs/decisions/`
  that mention a name the project removes, renames or reshapes (fixed text,
  ignoring case), with the number of matching lines. Each is the author's call:
  put it in scope or name it under `Not in`; a hit under `Not in` isn't listed.
They stay out of the proposed block.

It ends with the `allowed_paths` block that adds the named entries to today's,
leaving out an entry another new entry already covers. The
[project start check](#project-start-check) runs the named-file and sweep passes
and fails on what they list.

## Renumbering a patch series' lineages

[`tools/doc_scripts/renumber_adr_patches.py`](../../../tools/doc_scripts/renumber_adr_patches.py)
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

[`tools/doc_scripts/check_project_close.py`](../../../tools/doc_scripts/check_project_close.py) enforces the closing rule in
[ADR 0037 revision 3 (Decision and project workflow)](../../decisions/0037-decision-and-project-documentation-workflow/revision-003.md),
as [When a project finishes](../../projects/README.md#when-a-project-finishes) describes it:
each revision a deleted doc named on the base, in `decision:` or
`also_implements:`, must be `accepted` afterwards or named in either field by a
project doc that remains (`also_implements:` still gates no project's status).
A doc that names only `working` revisions is withdrawn and may be deleted.
A change that deletes no project doc isn't checked.

Unlike the scope check, it reads the docs as they stand **after** the
change, since it has to see what the change leaves behind; the base
supplies only the deleted doc's own `decision:`. A doc that doesn't parse
after the change fails the check rather than being skipped, and
`check_doc_drift.py` names it. A rename counts as a deletion plus an
addition, so a renamed project doc keeps its revision named.

Two PRs that each leave the other's project in place can both pass and
together leave a revision `approved` with no project. The generated
[Decisions awaiting a project](https://wenenhoe.github.io/homelab/project-planning/#decisions-awaiting-a-project)
view lists it, so the gap is visible but not blocked.

## Project start check

[`tools/doc_scripts/check_project_start.py`](../../../tools/doc_scripts/check_project_start.py) enforces the start rules in
[ADR 0037 revision 4 (Decision and project workflow)](../../decisions/0037-decision-and-project-documentation-workflow/revision-004.md)
and [revision 5](../../decisions/0037-decision-and-project-documentation-workflow/revision-005.md),
which [the lifecycle](../../projects/README.md#lifecycle) states: the decision revision a
new project may name, and what a change that sets a project `building` must carry. A rename
counts as an added doc.

The `Plan-Confirmed:` trailers are read from the commits between the merge-base
and the head, as the `Editorial-Fix:` trailer is, so a pull request merged with
a merge commit is judged by its own commits. The scope must
also be complete: the named-file and `sweep_terms` passes of the scope
suggestions find nothing the scope lacks and `Not in` doesn't decline. On a pull
request those passes read a checkout of the head, so a push from another branch
judges the same files CI does. A project
already `building` is not re-gated, but its scope can't narrow (it narrows only
when the project closes).

It reads the docs as they stand after the change, and a doc that does not parse fails the check.

The generator also warns, without failing, when more than
`ACTIVE_PROJECT_LIMIT` projects (`generate_doc_indexes.py`) are `building` or
`de-risking` at once.

## Accepted records check

[`tools/doc_scripts/check_accepted_records.py`](../../../tools/doc_scripts/check_accepted_records.py) holds the rules for
compacting accepted decisions in
[ADR 0037 revision 4 (Decision and project workflow)](../../decisions/0037-decision-and-project-documentation-workflow/revision-004.md),
described for the maintainer in
[`docs/decisions/README.md#compacting-accepted-records`](../../decisions/README.md#compacting-accepted-records).
It enforces two rules:

- **Frozen sections.** A revision that was `accepted` or `superseded` on the
  base keeps the parts the [Condense bullet](../../decisions/README.md#compacting-accepted-records)
  names frozen, and that bullet says what is not a change and which
  `Editorial-Fix: <path>` trailer excuses a file. Whitespace is collapsed
  before the comparison.
- **Removed lineages.** A lineage that held an `accepted` or `superseded`
  revision on the base and is gone afterwards must be a `former_ids` entry of
  a lineage that remains, or be listed in
  [`removed.md`](../../decisions/removed.md). The drift check also fails a
  number listed there that a lineage holds, or that is a former id too.

It reads the docs as they stand after the change for the removal rule, and a doc that does not parse
fails the check.

## Merge preparation

[`tools/doc_scripts/merge_adr_links.py`](../../../tools/doc_scripts/merge_adr_links.py)
runs nowhere in CI and is never run by an agent working a project: merging
decision records is the maintainer's operation
([ADR 0037 revision 4](../../decisions/0037-decision-and-project-documentation-workflow/revision-004.md)),
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
[retired-number check](doc-checks.md#retired-number-check) passes. The scan it shares with
this tool is `doc_retired.py`.

## Consolidation suggestions

[`tools/doc_scripts/suggest_adr_consolidation.py`](../../../tools/doc_scripts/suggest_adr_consolidation.py)
runs nowhere in CI and changes nothing. It lists decisions that read like
implementation detail (an accepted Decision that names many files), lineages
whose title, summary and Problem share many words, and clusters of three or
more lineages of one topic that all list one another in `related:`. With
`--report` it adds whether too many projects are active. The limits are constants at the top of the script. What a hit means
is the maintainer's call.

A pair or cluster the maintainer has read and kept apart is recorded in the
decisions README's table
[Records the report lists that stay separate](../../decisions/README.md#records-the-report-lists-that-stay-separate),
with a reason and, in its last column, each record's status when the row was
written (the status of its newest revision, so a pending `working` revision
counts). The report leaves a similar pair or tight cluster out when a row
covers it and none of its records has changed status. A row with a record that
changed status, is gone, or has no status recorded is listed under "Kept apart,
to read again" with the reason on file, whether or not the pair would be
reported now; a row the report cannot read is listed there too. Updating the
column is how a row is marked read again.
