# CI Doc Checks

The hooks and jobs that keep docs and project records consistent: index generation, the drift check, the project scope and close checks, and the Mermaid render check. How they sit in the pipeline is in [CI: PR Checks](pipeline.md).

## Doc index generation

[`tools/doc_scripts/generate_doc_indexes.py`](../../../../tools/doc_scripts/generate_doc_indexes.py),
wired into `.config/.pre-commit-config.yaml` as a local hook, positioned before
markdownlint/`check-doc-drift` below — it needs to run first so a bad
generation gets caught by the checks that follow, the same way a bad
hand-edit already is. Reads every `docs/projects/*.md` and every decision revision's
frontmatter and regenerates `docs/projects/README.md`'s Index and By
initiative tables and `docs/decisions/README.md`'s Lineages index in
place, validating each doc's frontmatter as it goes. Same
auto-fix pattern as the `ruff --fix` and `dclint-docker` hooks: a stale table
fails the commit and shows the regenerated diff, rather than silently
passing.

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
  linked from `decisions/README.md`. An `approved` or `accepted`
  revision has no open `Assumptions` entry — the hard gate in
  [`docs/decisions/README.md#assumptions`](../../../decisions/README.md#assumptions).
  Presence-of-a-bullet only, not whether the claim is genuinely
  resolved; that judgment call is still on whoever sets the status.
- A decision revision's heading and state: an unlettered revision 0
  opens with `# NNNN. <title>` (its lineage number and `title:`), and
  no revision carries a `**Status:**` body line, since the frontmatter
  `status` is the one record. Later and lettered revisions name their
  own solution in their heading, so only revision 0 is checked.
- Every project doc's `## Closing checklist` holds each item of
  `docs/projects/TEMPLATE.md`, in the same words (wrapping aside), so an
  item added to the template can't leave live projects without it. A
  project may add items of its own.
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
- Relative links (`./`, `../`) from a `.md` file to a config, script, or
  data file (`.yaml`, `.hcl`, `.py`, …) resolve to a real file, the same
  way `.md` links do.

Deliberately presence/shape checks, not content review — it can't tell
you a description is *wrong*, only that something's missing or a
documented thing no longer exists.

## Project scope check

[`tools/doc_scripts/check_project_scope.py`](../../../../tools/doc_scripts/check_project_scope.py) enforces the optional
`allowed_paths` field on project docs (see
[`docs/projects/README.md#scope`](../../../projects/README.md#scope) for what it means
and why). It runs in two places:

- **CI** — the `project-scope` job, on every pull request: the diff from
  the merge-base of the PR's base and head to its head. The merge-base,
  not the base tip, so a branch that is behind doesn't see main's newer
  commits as its own changes. The repo's other diff-based jobs diff
  `$BASE $HEAD` directly; this one deliberately doesn't.
- **pre-commit** — the `check-project-scope` hook, on what is staged,
  against `HEAD`. It sees only the current commit, so it is early
  feedback; CI is the authority, since it sees the whole PR. Under
  `pre-commit-checks`' `--all-files` run nothing is staged and it passes
  trivially.

In both, a project's scope is read from the doc **as it stands on the
base**, so a change can't widen its own scope and then use it. A project
doc that is new in the change has no scope yet. Renames and deletions
count as touching both paths. Path-level only: it can't tell whether an
edit inside an allowed file is the permitted one, and a change that never
touches its project doc isn't bounded.

## Project close check

[`tools/doc_scripts/check_project_close.py`](../../../../tools/doc_scripts/check_project_close.py) enforces the closing rule in
[ADR 0037 revision 2 (Decision and project workflow)](../../../decisions/0037-decision-and-project-documentation-workflow/revision-002.md):
deleting a finished project's doc must not leave the revision its
`decision:` names `approved` with no project naming it. A deleted doc
passes when that revision is `accepted` afterwards, or another project doc
that remains still names it in `decision:` (`also_implements:` doesn't
count, since it gates nothing). So the last project to close either
accepts the revision or leaves a `not-started` successor naming it for
whatever is unfinished. A change that deletes no project doc isn't
checked.

It runs in the same two places as the scope check, with the same
merge-base diff and the same staged-changes behavior:

- **CI** — the `project-close` job, on every pull request, judging the
  PR's head.
- **pre-commit** — the `check-project-close` hook, judging the index
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
