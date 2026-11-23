# The doc site renderer

`tools/doc_site` turns the three generated views ([`project-planning.md`](https://wenenhoe.github.io/homelab/project-planning/), [`decision-index.md`](https://wenenhoe.github.io/homelab/decision-index/) and [`coverage.md`](https://wenenhoe.github.io/homelab/dr-coverage/)) into a small static site. Its design is [ADR 0117 (Generated doc views)](../../decisions/0117-delivering-the-generated-doc-views-to-readers/revision-000.md). The views are not committed: a checkout writes them with the `generate-doc-indexes` hook ([`pre-commit.md`](pre-commit.md)), and the site is built from `main` and deployed on every push.

## One set of rows, two outputs

`doc_scripts/generate_doc_indexes.py` builds each generated section as rows: a `Table`, a `Note` where a table would be empty, `Groups`, a heading over several tables, or a `Grid`, numbers laid out ten to a row (`doc_scripts/view_model.py`). `generated_blocks()` returns them all, in the order the views hold them. The markdown written into a view and the HTML on the site are both formatted from those rows, so what a view says has one source, and the generator's markdown is byte-for-byte what it was before the rows existed.

A cell holds the markdown subset the views use: a link, an inline code span, or bold text, with a `|` escaped. `doc_site/markup.py` renders that subset and refuses anything else (a list, a code fence, a quote, a table, a heading or raw HTML in an introduction) so that a view which gains one fails the build instead of showing wrongly.

The decision index's By number section is a `Grid`: one row for each ten numbers, labelled by the first three digits (`011x`), and one cell for each number. A cell is a link to the lineage's current revision, `0030 → 0104` for a number merged into another (linked to where it went), `0013 demoted` or `dropped` for a number in `removed.md` (linked to the ledger), a dash for a number nothing holds and blank beyond the ends. On the site the grid is a list of cells and not a table, so on a phone each row breaks in two halves of five, and the Decisions count is the cells that hold a lineage. A lineage's name, state and notes are in its row under By topic, which puts the short name in a `Decision` column before the problem and the current solution.

By topic is `Groups`, which the site shows as tabs without a script: each group is a link beside its panel, and a rule in `assets/site.css` shows the panel of the group the address names, or the first when it names none, and hides the rest. Every group shows when the stylesheet is not applied, since the rule is what hides one. The row filter shows every group with a matching row while a filter is typed, so a row is found without knowing its group, and an address with a group's anchor, which is its heading's, opens that group.

## Design principles

Where a choice about a page is open, these decide it. Each says what the site does and what holds it.

- **Content first, no script needed.** A page is complete without JavaScript and, apart from its layout, without the stylesheet. The script adds the row filter and the menu's open button, and closes the contents list on a narrow screen; nothing a reader needs is reached only through it.
- **One source, two outputs.** The site adds navigation (menus, breadcrumbs, a contents list, tabs over lists of links) and never content. A page says what its markdown file says, and every page links to the file.
- **Show where you are.** A page names its place in its section in a breadcrumb, its own entry in the navigation, and its headings in a contents list; a heading of a long page links back to that list.
- **Orient, don't hide.** Scrolling is reduced by showing the shape of a page, not by folding its narrative away. Only a list of links is ever tabbed, and a rule that names that one page decides it, so no other document is hidden by a guess.
- **Every state has an address.** A heading, a tab and a section of a view each open from their anchor, so a link reaches them and the drift check holds the link. The text typed in a filter has no address.
- **Prose at a readable measure, data at full width.** See [the stylesheet](#the-stylesheet).
- **Targets and contrast.** A link in the menu, the contents list or a set of tabs is at least 44 pixels tall, and the stylesheet's colours come from one set of tokens in a light and a dark scheme. The layout check measures the text's size and not the targets or the contrast, so reading a page on a phone is still how those are found.

## Building the site

From `tools/`:

```sh
python -m doc_site --commit "$(git rev-parse HEAD)" --out /tmp/site
```

`--out` must be empty or absent. The site is `index.html`, which is the home page, one `<view>/index.html` for each view, one `projects/<name>/index.html` for each project, one `topics/<path>/index.html` for each topic doc, one `decisions/<lineage>/<revision>/index.html` for each decision revision, one `architecture/<name>/index.html` for each architecture doc, and `assets/`. A build that has a diagram to draw needs Google Chrome and `playwright`, as the layout check does. A build reads the tree and the commit it is given and nothing else (no clock, no git state, no network), so building twice from one tree and one commit gives the same bytes; a test holds that. `--commit` takes a full commit id; the command looks up that commit's date and hands both to the build. Without it the footer says "Local build".

## The footer

Every page's footer names the commit it was built from, as a link to that commit, with the commit's date in UTC, and credits Simple.css with a link to its licence. GitHub Pages serves a page for up to about ten minutes after a deployment, so a reader who suspects a page is old compares the commit in the footer with `main`. The workflow and the pull request job both pass `"$GITHUB_SHA"`. The licence is served as `assets/simple-licence.txt`, the text of `vendor/simple.LICENSE`, because the vendored stylesheet carries no notice of its own and the licence asks for one with every copy.

## Asset names

`assets/` names each file by the first ten hex digits of its sha256 (`site.3ba5af8963.css`, `simple.fb06245826.css`, `site.eedc88a706.js`) and every page names the file that goes with it, so a cache that holds an old page is never given the new stylesheet, nor a new page the old one. The second matters for `simple.css`: its `integrity` attribute refuses a stylesheet that is not the file the page was built with. The licence keeps its name; a page and a licence that differ cannot break a layout.

Each page takes its `# Title` and introduction from the view's file in [`tools/doc_scripts/view_intros/`](../../../tools/doc_scripts/view_intros) and its sections from the rows. The generator writes the markdown view from the same file and the same rows, so the view and the page say the same. An introduction holds no `##` section: a section written by hand would be dropped from the page, so the build refuses it. The page does not show the introduction as one block. A paragraph that opens with a section's name in bold (`**Roadmap** has one row for each initiative`) is that section's caption and sits under its heading. The first other paragraph is the lede under the title, and the remaining ones (a definition several sections share) are in a "How to read this page" disclosure. The generated markdown view still reads the whole file in order. A paragraph whose section is renamed is not lost: it falls into the disclosure, so rename the bold name with the heading. The links in an introduction are written for the view's place in `docs/`, and the drift checks read them in the generated view.

## The counts

The planning page and the decision index open with a strip of counts, each linking to the section it counts ([`summary.py`](../../../tools/doc_site/summary.py)). The planning page shows the projects in progress, startable and waiting (a link in a roadmap cell is a project; its "unblocks" count is not one), the decisions awaiting a project with how many of them are approved, and the open explorations. The decision index shows every decision, the open ones with how many are approved, and the superseded or abandoned ones. Each is counted from the rows of its section, so it cannot disagree with the table. A count that names a section the page lacks shows 0 and links nowhere; a view the module does not know has no strip.

## Roadmap chips

In the roadmap each project in the In progress, Startable and Waiting columns is a chip, a link named by the project without its `.md`, coloured by its column, with an "unblocks N" badge where the row has one. A cell that is anything other than a comma-separated list of project links (a dash, say) is rendered as text, so a change to the cell's form shows as plain links and loses nothing. No other table has chips.

## Document pages

A document with a page of its own is a markdown file of the repository, shown as it reads on GitHub ([ADR 0119 (Docs as site pages)](../../decisions/0119-reading-the-documentation-tree-away-from-github/revision-000.md)). The projects, the topic docs, the decision revisions, the architecture docs and the READMEs of `docs/projects/`, `docs/topics/`, `docs/decisions/` and `docs/architecture/` have pages, at `projects/<name>/`, `topics/<path>/`, `decisions/<lineage>/<revision>/`, `architecture/<name>/`, `projects/`, `topics/`, `decisions/` and `architecture/`, and the list of removed decision numbers is at `decisions/removed/`; the README of `docs/` is the home page, the `TEMPLATE` files have none, and the generated coverage view is a view, not a topic doc. `doc_site/documents.py` reads the body with a CommonMark library (`markdown-it-py`), so lists, tables and code blocks follow GitHub's rules, and it refuses what it has no rule for, as `markup.py` does for the views: raw HTML and an image. An HTML comment is dropped, as GitHub does not show it. An error names the file and the line. The `check-doc-drift` hook imports the site to read its anchors, so it pins `markdown-it-py` beside `jinja2` in `.config/.pre-commit-config.yaml`; a new library the renderer imports goes there too.

- The first top-level heading is the page's title, and the front matter is read for a header above the body: the status as a pill, whether the project is blocked, the project it is part of, its decision, the projects it waits on as links to their pages, and its summary as the lede.
- A decision revision's header names its record (the lineage and the revision), its state as a pill, and, where it has them, `light` weight, the revision it supersedes and the one that supersedes it, the lineage it narrows, the lineages it relies on with the reason for each, the lineages related to it and the projects that name it in `decision:` or `also_implements:`. A lineage is linked at its current revision and shown as `ADR 0117 (Generated doc views)`, the form the docs cite it in; one that is no longer in the tree is named and not linked. A superseded revision carries a notice above the header that names its successor. The generated decision index links each row to these pages.
- A decision page whose lineage has two or more revisions lists all of them under the header, each with its state, the current one marked and the one being read marked and not linked. Every decision page ends with links to the decisions before and after it by number, each at its current revision.
- A heading has the anchor GitHub gives it, and a `##` or `###` heading is in the menu's list of the page.
- A document page with four or more headings in its menu lists them under "On this page" on the page, between its introduction and its first section, and each `##` heading ends with a link back to the list. The list is a `<details open>`, so it shows with no script or stylesheet; at 1100 pixels and wider it sits in the column beside the prose, which keeps its measure and leaves tables and code the width the column does not take, and below that `assets/site.js` closes it so a phone starts on the text, and opens it again if the screen widens. It does not stay on screen as the page scrolls: the link at each heading is how a reader gets back to it. A heading whose anchor is `on-this-page` stops the build, as the list's own address. The home page, the views and the Topics index have no such list.
- The Topics index shows each `##` group as a tab, as the decision index shows its By topic groups: a link beside its panel, the panel of the group the address names (the first when it names none) shown by the stylesheet alone, a filter over the rows that shows every group with a match, and every group showing when the stylesheet is not applied. The group's anchor is its heading's, so the `topics/#<group>` link in a topic page's breadcrumb opens that tab. `TABBED_DOCUMENTS` in `site.py` names this one page; no other document is tabbed because of how it looks. The tabs are made from the README's own headings and links, so the document does not change.
- The home page is the README of `docs/`, its address following its path like every other page: the tiles of the navigation's entries come first and the README's body follows under its title, with its headings in the menu. A link to that README from another page goes to the home page.
- The navigation lists Planning, Projects, Decisions, Topics, Architecture and DR coverage, and a page under `projects/` or `topics/` marks its own entry, as a decision page marks Decisions, whose entry opens the index. The home page has a tile for each.
- Each section opens on a list. Projects opens on the projects with their status and initiative, built from the front matter, above the README, which sits under a "Guide to projects" heading that a link in the breadcrumb reaches; Decisions opens on the decision index, and its README is the guide that the breadcrumb links; Topics and Architecture open on their READMEs.
- A page under a section starts with a breadcrumb: the section, linked unless the page is its landing, then where the page is in it (a decision's `ADR` and revision, a topic's group when the topics README has a heading for it, otherwise the title). A page that has the section's guide shows it at the end of the line. A README of a section is its landing, so every page of the section is one link from it.
- A link to a page of the site goes to it with its anchor kept, and a link to any other file goes to it on GitHub, as in a view. A link from a project to a view or to another project is therefore a link between pages.
- A list item that starts `[ ]` or `[x]` is a disabled box, so a closing checklist reads as one. The page does not change the file: the box is not a control.
- A table takes the same card layout as a view on a phone, each cell labelled by its column, and a `Status` cell is a pill. A code block wraps, as the layout check refuses a block that scrolls sideways.
- Every page links to its file on GitHub, where the document can be edited.

## Diagrams

A Mermaid block is drawn to SVG during the build, so no script reaches a reader and a diagram shows without one. `doc_site/diagrams.py` runs the bundle `vendor/mermaid.min.js` in the installed Chrome, headless, in a page made from nothing with every request refused, at Mermaid's strict security level. Every diagram of the site is drawn in one browser session, twice, in Mermaid's light and dark themes, and the page holds both: the stylesheet shows the one the reader's `prefers-color-scheme` asks for. The drawing takes about ten seconds for the repository's diagrams. A diagram that does not draw stops the build with the file, the line of its fence and Mermaid's message. The seed Mermaid uses for the outline of a node is fixed, so two builds of one tree are the same bytes, which a test holds.

The block's source is not shown; GitHub shows the diagram too, and a reader who wants the source opens the file there. A diagram is scaled to the width of its column, and the check holds it to the page like any other block. `page_anchors`, which the drift check calls, draws nothing, because an anchor does not depend on it.

## Anchors and links

Every heading has the anchor GitHub gives it: lowercase, everything but letters, digits, spaces, hyphens and underscores removed, spaces as hyphens, a repeat numbered `-1`, `-2`. Docs that link to a section of a view therefore reach the same section on the site. A link from one view to another goes to its page, with the anchor kept; a link to any other file goes to it on GitHub.

## The stylesheet

The page is styled with [Simple.css](https://simplecss.org/) (MIT), committed at `tools/doc_site/vendor/simple.min.css`, with its licence beside it. `vendor/simple.pin` names the npm package, the version, the file taken from it, that file's sha256 and the GitHub repository the package is built from. The site makes no request to a third party; nothing is fetched at build time or by a reader's browser.

The Mermaid bundle is vendored the same way, as `vendor/mermaid.min.js` with `vendor/mermaid.pin` and `vendor/mermaid.LICENSE` (MIT, copied from the package; an update does not rewrite it). Its pin has `source = registry`: the repository builds the bundle and does not commit it, so there is no tagged file to compare, and `--upstream` holds the file and the pin to the registry's tarball alone. Both pins are checked by the one test, by `python -m doc_site.vendor` without arguments, and the build checks the bundle's hash before it runs it.

- A test fails when the committed file's hash differs from the pin.
- `python -m doc_site.vendor --upstream` also compares both with the tarball the npm registry serves for that version, read in memory and never extracted, and with the same file at the repository's `v<version>` tag, so a tarball that differs from the published source fails.
- `python -m doc_site.vendor --pin simple --update VERSION` (or `--pin mermaid`) replaces the file and the pin together, and writes nothing when the tarball and the tag differ.

The stylesheet has no trailing newline and the bundle has trailing spaces, as published, so `end-of-file-fixer` and `trailing-whitespace` skip `tools/doc_site/vendor/` and the drift check's anchor scan skips `tools/tests/doc_site/`, whose fixtures hold example links to files that exist only in their temp trees.

Renovate moves only the `version` line of either pin, because it has no digest for a file inside an npm tarball. The pull request it opens fails the pin test until `--update` has been run for that pin with that version, which writes the file and the new hash in one step.

The card layout, the menu drawer, the row filter and the contents list are `assets/site.css` and `assets/site.js`, which belong to this repository. The page works without JavaScript; the script only adds the filter and the drawer's open button, and closes the contents list on a narrow screen.

A document page sets its prose (paragraphs, lists, quotes, headings, the lede and the notice) to one reading measure, and lets its tables, code blocks and figures use the width of the page, less the column of its contents list where it has one. A view sets no measure on its lede, caption or legend, so they run as wide as the table and the filter under them.

## The layout check

```sh
python -m doc_site.layout /tmp/site
```

The check serves a built site on localhost and opens every page in the installed Google Chrome, headless, at 360, 390, 768 and 844 pixels wide and 800 tall (two portrait phones, a small tablet and a wide screen), and at 844 by 390, a phone in landscape. A page with a contents list or tabs is opened at 1280 by 800 as well, the width where the list has a column of its own; other pages are not, since nothing about them changes there. A page is loaded once and resized to each size, and the pages are dealt out to four browsers that run side by side, so the time is a fraction of loading every page at every size in one browser; the errors come out in the order of the pages and then of the sizes, whichever browser found them. A script that calls `check` from outside the module needs the usual `if __name__ == "__main__"` guard, as the browsers are started as new processes. It needs Chrome and `playwright` (a dev dependency), and downloads nothing; the runner image has Chrome. A page fails when it scrolls sideways, when an element ends past the right edge of the screen, when a block holds text wider than the block (a table cell or a card cell that overflows its box), when visible text is under 12 pixels, when a bar that stays on screen (`position: sticky` or `fixed`, a menu drawer aside) takes more than a fifth of the height, or when a link to a heading of the page leaves the heading under such a bar. The header is sticky except on a screen under 30rem tall, where it scrolls away, so that landscape check passes; `html` has a `scroll-padding-top` that keeps a linked heading clear of it. Text hidden for screen readers, such as the table header that the card layout hides, is not on the screen and is not measured. Where the page has a menu button the check also opens the drawer, holds it to the same rules, and fails if the button opens nothing. Every error names the page, the width and the element.

`python -m doc_site.layout --sample /tmp/site` opens a fixed set instead of every page: the home page, every page one directory deep (the three views and the landing of each section, the Topics index among them), the first page of each of Projects, Decisions, Topics and Architecture, and the page with a contents list that has the most markup, which is the longest document. It takes about seven seconds where the full run takes about a minute. The set does not grow with the number of pages, and `layout.MAX_SAMPLE` bounds it, which a test holds with a site of hundreds of pages, so a new view or section that pushes the sample past it fails there and not as a slow pull request.

A check on what the page measures cannot see a layout that is readable by the numbers and wrong to the eye, such as words broken in the middle in a narrow column. Reading the page on a phone is still how that is found.

## Publishing

`.github/workflows/pages.yml` runs on every push to `main` and on demand. It has two jobs, so that what builds does not hold what deploys:

- `build` has a read-only token. It builds the site, runs the layout check and uploads the result as the Pages artifact, in that order, so a layout that breaks a phone is never deployed.
- `deploy` runs no repository code. It holds `pages: write` and `id-token: write` and no `contents` permission at all, so it writes a deployment and no branch or tag. It runs in the `github-pages` environment.

One run goes at a time and one waits, and a newer waiting run replaces an older one, so a burst of merges ends with the newest commit deployed. A run that has started is never cancelled halfway through a deployment. Every action is pinned by commit and kept current by Renovate. `tools/tests/doc_site/test_pages_workflow.py` fails a `contents: write` on any job or on the workflow, a deploy job with permissions other than those two, a layout check that does not sit between the build and the upload, and an action that is not pinned by commit.

Two settings are the maintainer's and live on GitHub: the repository's Pages source is GitHub Actions, and the `github-pages` environment accepts a deployment from `main` only. The workflow sets neither, and a deployment from another branch is refused by the environment, not by this file.

The `doc-site` job in `pr-checks.yml` runs the same build and layout check on a pull request that changes the renderer, the generator or what they read ([change scoping](ci/change-scoping.md)). It deploys nothing and has no write permission.

## Subresource integrity

The stylesheet's `<link>` carries an `integrity` attribute with the sha384 of the vendored file, computed when the site is built from the bytes it writes, so it has no pin of its own to keep in step with `simple.pin` and a stylesheet update changes it with no further step. A test holds the attribute to the file.

## Linking a view

A doc links a generated view through its page on the site, `https://wenenhoe.github.io/homelab/<page>/`, with the same `#anchor` it would have used on the file: `project-planning/`, `decision-index/` or `dr-coverage/`. A link to the file's path fails the drift check, and so does a link to a page that does not exist or to an anchor that no heading on the page has ([the check](ci/doc-checks.md)). This holds for a link to a document's page (`topics/<group>/<doc>/`, or `topics/#<group>` for a tab of the Topics index) as for a view's, and an anchor can be a heading's, a section's or `on-this-page`, the list of a long page. The anchors are the ones GitHub gives the headings, so a link that worked on the file works on the page. The site is a minute or so behind a merge, so a link to a heading added in the same pull request reaches the page once the deployment has finished, and the drift check, which builds the pages from the tree, accepts it before then.

A table row's details are on the page it names, not behind its own link: the coverage table has no per-app anchors, and a doc that needs one app's row names the app.
