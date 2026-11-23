---
id: PROJ-doc-site-pages
title: "Doc site pages"
type: project
status: building
blocked: false
summary: "Publish the projects, topic docs, decisions and architecture docs as pages of the doc site, with front-matter headers, links between them, a home and section landings that lead to them, a decision index laid out for finding a decision, and diagrams drawn at build time, then accept the decision."
decision: ADR-0119/0
allowed_paths:
  - tools/doc_site/**
  - tools/tests/doc_site/**
  - tools/doc_scripts/check_doc_drift.py
  - tools/tests/doc_scripts/test_check_doc_drift.py
  - tools/doc_scripts/generate_doc_indexes.py
  - tools/doc_scripts/view_model.py
  - tools/doc_scripts/view_intros/decision-index.md
  - tools/tests/doc_scripts/test_generate_doc_indexes.py
  - pyproject.toml
  - uv.lock
  - .github/workflows/pr-checks.yml
  - .github/detect-changes-filters.yml
  - .github/renovate.json5
  - .config/.pre-commit-config.yaml
  - docs/topics/engineering/doc-site.md
  - docs/topics/engineering/ci/doc-checks.md
---

# Doc site pages

Puts the publication of the documentation tree into practice as [ADR 0119 (Docs as site pages)](../decisions/0119-reading-the-documentation-tree-away-from-github/revision-000.md)
decides. It is staged because each kind of document needs a different part of the renderer, projects first as they hold the least
markup, and the checks that scale with the page count can only be set once the pages exist. Each stage is one pull request.

## Scope

- A document renderer in `tools/doc_site/`: a CommonMark body that refuses a block it has no rule for, a header from the front matter,
  links between pages, and a source link on every page. The `check-doc-drift` hook pins the renderer's library in
  `.config/.pre-commit-config.yaml`, as it imports the site.
- Pages for the projects, the topic docs with their index, the decision revisions, the READMEs and the architecture docs; none for
  `explorations/` or the `TEMPLATE` files.
- Mermaid blocks drawn to SVG during the build from a pinned bundle in `tools/doc_site/vendor/`, in a light and a dark rendering. The
  Renovate rule that moves the stylesheet's pin also moves the bundle's.
- Navigation entries for Topics, Projects, Decisions and Architecture, and the rows of the generated views linking to the pages.
- A home page that carries `docs/README.md` beside the tiles; a landing for each section that opens on its list, with the section's
  README one link away from every page of it; and a breadcrumb and a lineage strip on a decision page.
- A reading measure for the prose of a document page, and the generated decision index laid out for finding a decision: its numbers ten
  to a row, the short name beside the problem, and the topic groups as tabs.
- The checks the page count needs: the doc-site pull request job for a changed document, and the layout check on a sample of
  document pages for each kind.
- `doc-site.md` and the topic docs it feeds, extended as each stage lands.

Not in: tabs or any other hiding of the content of an authored doc, search, editing or commenting, a view of another commit, documents outside `docs/`, and any edit to the documents under `docs/` apart from `docs/topics/engineering/doc-site.md` and `docs/topics/engineering/ci/doc-checks.md`: the site reads them and changes none.

## Decision

[ADR 0119 (Docs as site pages)](../decisions/0119-reading-the-documentation-tree-away-from-github/revision-000.md), `approved`.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | The renderer and the projects | Done | Every project doc has a page with a header from its front matter, its checklists as boxes and a source link; a block the renderer has no rule for fails the build, with a test that does so; the planning view's rows link to the pages; the layout check passes on them |
| 2 | Topic docs and diagrams | Done | Every topic doc and the topics index has a page, relative links to rendered documents resolve to pages with their anchors and other repository files go to GitHub, and every Mermaid block is drawn at build time in both renderings from a pinned bundle whose hash a test holds; a diagram that fails to render fails the build; the navigation lists Topics and Projects |
| 3 | Decisions | Done | Every decision revision has a page whose header names its state, what it supersedes or is superseded by, what it relies on and the projects that implement it; the decision index rows link to the pages; a superseded revision is marked as one |
| 4 | Reading flow | Not started | The home page carries `docs/README.md`; the architecture README and each architecture doc have a page, with their diagrams, under an Architecture entry; Projects, Decisions, Topics and Architecture each open on a list (for Projects, the projects with their status and initiative above the README) and every page of a section links to its README the same way; a decision page has a breadcrumb, lists every revision of its lineage with its state and the current one marked, and links to the previous and next ADR by number; a document page's prose has one reading measure, and a view's lede, caption and legend span the width of its table and filter; the layout check passes on them |
| 5 | Decision index | Not started | By number is a grid of ten numbers to a row, in the markdown view and on the site, and a number merged into another or removed is a cell that says so and links to where it went; a By topic row names its decision by its short name beside its problem and current solution; the By topic groups are tabs on the site, each reachable by its anchor and by the filter, with every group showing when the stylesheet is not applied; a lineage is in the grid and in one topic group, as before |
| 6 | The checks that scale | Not started | A pull request that changes a document runs the doc-site job; the layout check covers the views and a sample of document pages for each kind, including the home page, a section landing and an architecture page, in time bounded by a test on the sample's size; the drift check holds a link to a site page to a page and an anchor that exist |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] Every markdown file under `docs/` outside `explorations/` and the `TEMPLATE` files has a page, and no exploration has one.
- [ ] A document with a block the renderer has no rule for fails the build.
- [ ] Every Mermaid block appears as SVG in a light and a dark rendering, and no page needs a script to be read.
- [ ] The home page carries `docs/README.md`, and each section opens on its list with its README one link away.
- [ ] The decision index lays its numbers out ten to a row, in the markdown view and on the site.
- [ ] A link from one document to another works on the site and keeps its anchor; a link to a file that is not a page goes to GitHub.
- [ ] Building the site twice from one commit gives the same bytes.
- [ ] The deploy job's permissions are unchanged.
- [ ] ADR 0119 is `accepted`.

## Agent handoff

Stop conditions are in [`README.md#stop-conditions`](README.md#stop-conditions); they apply without being restated here.

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced, once the project is `building`.
- **Must not change:** the deploy job's permissions; the generated views' row content, except as stage 5 changes the decision index; any decision revision other than ADR 0119's own.
- **Relevant files and interfaces:** `tools/doc_site/`, `tools/tests/doc_site/`, `tools/doc_scripts/generate_doc_indexes.py` and its view model for stage 5, the `doc-site` job in `pr-checks.yml` and the `doc_site`
  filter in `.github/detect-changes-filters.yml`, [`doc-site.md`](../topics/engineering/doc-site.md).
- **Required checks:** `pre-commit run --all-files`, the Python unit tests, the doc-site build and layout check.

## Risks

- The layout check opens each page at five sizes, so a full run over every page is too slow for a pull request; stage 6 sets the sample.
- A page can differ slightly from GitHub's rendering of the same file; the source link on every page is the reader's way to compare.
- The bundle and the `markdown-it-py` dependency sit on the stop list, so stages 1 and 2 each stop for confirmation; stages 4 to 6 change `tools/` and stop too.
- Tabs can hide a row from find-in-page and from a link to it, and a page needs no script to be read, so the tabs work from the stylesheet alone and a row is found through its anchor or the filter.
- The markdown view is what GitHub shows, so stage 5's grid has to stay readable there as well as on the site.

## Open items

None.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
