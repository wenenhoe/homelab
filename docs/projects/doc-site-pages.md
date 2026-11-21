---
id: PROJ-doc-site-pages
title: "Doc site pages"
type: project
status: building
blocked: false
summary: "Publish the projects, topic docs and decisions as pages of the doc site, with front-matter headers, links between them, and diagrams drawn at build time, then accept the decision."
decision: ADR-0119/0
allowed_paths:
  - tools/doc_site/**
  - tools/tests/doc_site/**
  - tools/doc_scripts/check_doc_drift.py
  - tools/tests/doc_scripts/test_check_doc_drift.py
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
- Navigation entries for Topics, Projects and Decisions, and the rows of the generated views linking to the pages.
- The checks the page count needs: the doc-site pull request job for a changed document, and the layout check on a sample of
  document pages for each kind.
- `doc-site.md` and the topic docs it feeds, extended as each stage lands.

Not in: search, editing or commenting, a view of another commit, documents outside `docs/`, and any edit to the documents under `docs/` apart from `docs/topics/engineering/doc-site.md` and `docs/topics/engineering/ci/doc-checks.md`: the site reads them and changes none.

## Decision

[ADR 0119 (Docs as site pages)](../decisions/0119-reading-the-documentation-tree-away-from-github/revision-000.md), `approved`.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | The renderer and the projects | Done | Every project doc has a page with a header from its front matter, its checklists as boxes and a source link; a block the renderer has no rule for fails the build, with a test that does so; the planning view's rows link to the pages; the layout check passes on them |
| 2 | Topic docs and diagrams | Not started | Every topic doc and the topics index has a page, relative links to rendered documents resolve to pages with their anchors and other repository files go to GitHub, and every Mermaid block is drawn at build time in both renderings from a pinned bundle whose hash a test holds; a diagram that fails to render fails the build; the navigation lists Topics and Projects |
| 3 | Decisions | Not started | Every decision revision has a page whose header names its state, what it supersedes or is superseded by, what it relies on and the projects that implement it; the decision index rows link to the pages; a superseded revision is marked as one |
| 4 | The checks that scale | Not started | A pull request that changes a document runs the doc-site job; the layout check covers the views and a sample of document pages for each kind in time bounded by a test on the sample's size; the drift check holds a link to a site page to a page and an anchor that exist |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] Every markdown file under `docs/` outside `explorations/` and the `TEMPLATE` files has a page, and no exploration has one.
- [ ] A document with a block the renderer has no rule for fails the build.
- [ ] Every Mermaid block appears as SVG in a light and a dark rendering, and no page needs a script to be read.
- [ ] A link from one document to another works on the site and keeps its anchor; a link to a file that is not a page goes to GitHub.
- [ ] Building the site twice from one commit gives the same bytes.
- [ ] The deploy job's permissions are unchanged.
- [ ] ADR 0119 is `accepted`.

## Agent handoff

Stop conditions are in [`README.md#stop-conditions`](README.md#stop-conditions); they apply without being restated here.

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced, once the project is `building`.
- **Must not change:** the deploy job's permissions; the generated views' row content; any decision revision other than ADR 0119's own.
- **Relevant files and interfaces:** `tools/doc_site/`, `tools/tests/doc_site/`, the `doc-site` job in `pr-checks.yml` and the `doc_site`
  filter in `.github/detect-changes-filters.yml`, [`doc-site.md`](../topics/engineering/doc-site.md).
- **Required checks:** `pre-commit run --all-files`, the Python unit tests, the doc-site build and layout check.

## Risks

- The layout check opens each page at five sizes, so a full run over every page is too slow for a pull request; stage 4 sets the sample.
- A page can differ slightly from GitHub's rendering of the same file; the source link on every page is the reader's way to compare.
- The bundle and the `markdown-it-py` dependency sit on the stop list, so stages 1 and 2 each stop for confirmation.

## Open items

None.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
