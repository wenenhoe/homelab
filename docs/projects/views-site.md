---
id: PROJ-views-site
title: Views Site
type: project
status: building
blocked: false
summary: Publish the decision index, the planning view and the disaster-recovery coverage table as a GitHub Pages site built from main, then stop committing them and generate them in a checkout.
decision: ADR-0117/0
allowed_paths:
  - tools/doc_site/**
  - tools/tests/doc_site/**
  - tools/doc_scripts/**
  - tools/tests/doc_scripts/**
  - tools/progress_log/**
  - tools/tests/progress_log/**
  - tools/land_series/**
  - tools/tests/land_series/**
  - pyproject.toml
  - uv.lock
  - .github/workflows/pages.yml
  - .github/workflows/progress-log.yml
  - .github/workflows/pr-checks.yml
  - .github/detect-changes-filters.yml
  - .github/renovate.json5
  - .githooks/**
  - .pre-commit-config.yaml
  - .config/.pre-commit-config.yaml
  - .gitignore
  - README.md
  - docs/**
sweep_terms:
  - generated-views
  - pre-applypatch
  - post-applypatch
  - decision-index.md
  - project-planning.md
  - coverage.md
---

# Views Site

Publishes the three generated views as a static site on GitHub Pages and, once the site is trusted, stops committing them, as [ADR 0117 (Generated doc views)](../decisions/0117-delivering-the-generated-doc-views-to-readers/revision-000.md) decides. It is staged because the site must exist and be trusted before any doc stops pointing at the committed files.

## Scope

A renderer in `tools/doc_site/` that builds the decision index, the planning view and the coverage table as pages from the rows the generator already computes, with the vendored `simple.css` it pins and the card and drawer layer on top. A deploy workflow, `.github/workflows/pages.yml`, with its actions pinned by commit and kept current by Renovate, and a topic doc for the site. Then the docs that link a view, the generator, the hooks and the checks that read the committed files, and the landing tool's handling of them.

The renderer reads only the tree, so two builds of one commit are the same page. The generator stays the one source of what a view says: its markdown and the site's pages are formatted from the same rows, and a test holds the markdown unchanged.

Not in: the repository's Pages source and the `github-pages` environment's branch rule, which the maintainer sets by hand (see the acceptance criteria), the text of ADR 0112, whose new revision is the maintainer's decision, any page for a doc other than the three views, and two files that only name a view as an example, `tools/tests/review_criteria/test_criteria.py` (a hook path used as sample input) and `ansible/tests/test_resolved_apps_consumers.py` (a list of files a sweep skips).

## Decision

Implements [ADR 0117 (Generated doc views)](../decisions/0117-delivering-the-generated-doc-views-to-readers/revision-000.md), `approved`. Its Decision is two steps, and so is this plan: Stages 1 and 2 publish the site while the views stay committed, and Stages 3 to 5 begin only after the maintainer says the site is trusted. The parts of [ADR 0112](../decisions/0112-landing-a-series-of-dependent-changes-on-main/revision-001.md) that describe the views need a new revision once this one is accepted.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | The row model and the renderer: each view's tables are built as rows that the markdown and the pages are both formatted from, with `simple.css` vendored at a pinned version and hash, the card and drawer layer, and Jinja2 declared as a dependency | Done | The markdown of the three views is byte-for-byte what the generator wrote before, a test builds each page twice from a fixture tree and gets the same bytes, every heading has an anchor equal to the one GitHub gives it, a test fails when the vendored file's hash differs from its pin, and Renovate has a rule that moves the pin's version, with a command that replaces the file and the hash together and a check of both against the registry's tarball and the repository's tag |
| 2 | The deploy workflow, the layout check and the topic doc | Done | `.github/workflows/pages.yml` builds on every push to `main` with a concurrency group and `cancel-in-progress: false`, runs the layout check at portrait and landscape phone widths, and deploys from a job that holds `pages: write` and `id-token: write` and no `contents: write`; every action is pinned by commit; a workflow test fails a `contents: write` on that job; `progress-log.yml`'s header no longer calls itself the only write token; `pr-checks.yml` builds the site and runs the layout check when the renderer, the generator or their inputs change; the site is live at its address with the three views |
| 3 | The docs link the site | Done | No doc outside decision revisions links a view by path; an anchor link goes to the site's page and the same anchor; the 3 links inside decision revisions are changed as editorial; the drift check passes with the views still committed |
| 4 | Stop committing the views | In progress | The three files are not tracked and are ignored; `post-merge` and `post-checkout` hooks and `generate_doc_indexes` write them in a checkout; `check_doc_drift.py`, `doc_scope.py`, `classify.py` and `merge_adr_links.py` read or name them without a committed file; the apply hooks and the list they read are gone with the two tests of them |
| 5 | The landing tool and its docs drop the views | Not started | `land_series` no longer resets generated views between layers or applies one patch per `git am`, its tests and `landing-a-series.md`, `pre-commit.md` and `checks-without-docker.md` describe the replay without them, and a series that edits a view's source lands with a plain `git am` |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1

The generator's `render_*` functions return a markdown string today. The rows move into a small structure per table (headers, cells, and for a status cell its key), and the markdown renderer formats that structure; the generator's existing tests and the drift check over the real tree are what hold the markdown unchanged. The renderer in `tools/doc_site/` reads the same structure, so it never parses markdown.

`simple.css` is vendored as a single file with its version and sha256 in a pin file beside it, the way the repository pins a release asset elsewhere. Renovate has no digest for a file inside an npm tarball, so its rule moves the version only; `python -m doc_site.vendor --update` then takes the file from the registry and writes it and the hash together, and `--upstream` checks both against the published tarball and the repository's file at the same version's tag, which `--update` also requires before it writes anything. The card layer stacks a row as a card under 62rem, never breaks inside a word in a table cell, hides empty cells, and puts the identifier, the status pill and the title in a fixed order; below 62rem the menu is a left drawer opened by a button, and above it a plain navigation. The drawer is a `<dialog>`, so its focus handling comes from the browser, and without scripts the links show as an ordinary navigation.

### Stage 2

The layout check opens each page in the headless Google Chrome that the runner image carries (driven by `playwright`, a dev dependency that downloads no browser), at 360, 390, 768 and 844 pixels and fails a page that scrolls sideways, a table cell wider than its card, a text smaller than 12 pixels, or a cell whose text overflows its box. It runs in the workflow before the artifact is uploaded, so a layout change that breaks a phone does not deploy. The stylesheet's `<link>` carries a sha384 `integrity` attribute computed at build time from the vendored bytes, so it has no second pin. The workflow is two jobs: `build` has a read-only token and uploads the artifact, and `deploy` runs no repository code and holds `pages: write` and `id-token: write` only. The Pages source and the `github-pages` environment are the maintainer's settings, and the site is live with the home page and the three views.

### Stage 3

Every markdown link to a view by path (69 of them in 37 files, 3 inside decision revisions) became a link to the view's page with the same anchor. A link target is not part of a revision's frozen sections, so those three needed no editorial trailer. The drift check now fails a markdown file that links a view by its path, and fails a link to the site that names a page that does not exist or an anchor no heading on the page has; it takes the headings from the pages built from the tree, so it accepts a link to a heading added in the same pull request. The check is in place before the views stop being committed, so Stage 4 only removes what read the files. The index of `docs/topics/README.md` keeps the coverage table's path as the text of its row, which the index check reads, and Stage 4 drops that rule with the file.

### Stage 4

The apply hooks cannot replay the commit that stops tracking the views: they `git add` each listed view, which fails once git ignores it, and they read the list from the tree being replayed, which that commit deletes. A hook runs from the clone it is installed in, so a hook change reaches a replay only after the clone has pulled it. The stage therefore lands in two pull requests, each its own run of the tool. The first makes the hooks leave an ignored view, and a missing list, alone. The second, run once the maintainer's clone has the new hooks, moves each view's title and introduction to `tools/doc_scripts/view_intros/`, one file per view, which the generator writes the view whole from, byte for byte as before and which the site reads too; then stops tracking the views and deletes the apply hooks and the list, the two tests of them and `generated_views.py`. The checks that read the files change with it: the drift check no longer reads the decision index to see that every lineage is linked in it, since the generator writes that table from the same lineages, and `doc_scope.py` and `classify.py` stop naming files that no change can touch.

## Acceptance criteria

- [x] The site is live at the repository's Pages address with the decision index, the planning view and the coverage table, and a phone reads each in portrait and landscape without sideways scrolling.
- [ ] The repository's Pages source is GitHub Actions and the `github-pages` environment accepts a deployment from `main` only; a deployment from another branch is refused.
- [x] The deploy job has no `contents: write`, and `zizmor` reports nothing on the workflow.
- [ ] No tracked file is a generated view, and a checkout that runs the generator has all three as ignored files with the content the site shows.
- [ ] A series that edits a view's source lands on `main` with a plain `git am`, and two series that each add a decision do not conflict.
- [x] No doc links a view by a path that is not in the tree, and every anchor link into a view reaches its section on the site.
- [x] The site's `simple.css` is the pinned version, a test fails when its hash differs from the pin, and Renovate opens a pull request that moves the version, which the vendor command completes with the file and the hash.
- [ ] ADR 0117 is `accepted`, and a new revision of ADR 0112 describes landing without the views.

## Agent handoff

Keep this section: all work here is agent work, so no building project is exempt. Stop conditions are in
[`README.md#stop-conditions`](README.md#stop-conditions); they apply
without being restated here.

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** the ADR's Decision, the repository's Pages and environment settings, the rulesets, and ADR 0112 (its new revision is the maintainer's to approve).
- **Starts after the maintainer's word:** Stage 3 and every stage after it. Stages 1 and 2 leave every committed view and every link as it is; whether the site is trusted is the maintainer's call, and it is not inferred from a deployment succeeding.
- **Relevant files and interfaces:** `tools/doc_scripts/generate_doc_indexes.py`, `generated_views.py` and the three view files; `.githooks/`; `tools/land_series/` for the reset and the one-patch-per-`git am` rule; `warm-caches.yml` for a workflow with a concurrency group; `progress-log.yml` and [`progress-log.md`](../topics/engineering/progress-log.md) for the one other write token.
- **Required checks:** `pre-commit run --all-files`, `uv run pytest` from `tools/`, and the layout check from Stage 2.

## Risks

- Anchors that GitHub generates for a heading and the site's anchors can differ for a heading with punctuation or a link; Stage 1's test compares them for every heading, and a heading that cannot match is renamed.
- The site is a minute or so behind a merge, so a doc linked right after a change merges can show the previous page.
- A vendored stylesheet that its publisher stops maintaining still works, but gets no fixes for later browsers; the Renovate rule shows when upstream goes quiet.

## Open items

- The maintainer adds `doc-site` to the `main` and `maintenance-and-develop` rulesets with the commands in [`branching.md`](../topics/engineering/branching.md#adding-a-required-check). The docs already say 17 checks are required.
- Whether the checkout's generator runs from the two hooks or only by hand; Stage 4 settles it from how the hooks behave on a rebase.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
