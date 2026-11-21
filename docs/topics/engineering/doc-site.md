# The doc site renderer

`tools/doc_site` turns the three generated views ([`project-planning.md`](https://wenenhoe.github.io/homelab/project-planning/), [`decision-index.md`](https://wenenhoe.github.io/homelab/decision-index/) and [`coverage.md`](https://wenenhoe.github.io/homelab/dr-coverage/)) into a small static site. Its design is [ADR 0117 (Generated doc views)](../../decisions/0117-delivering-the-generated-doc-views-to-readers/revision-000.md). The views are not committed: a checkout writes them with the `generate-doc-indexes` hook ([`pre-commit.md`](pre-commit.md)), and the site is built from `main` and deployed on every push.

## One set of rows, two outputs

`doc_scripts/generate_doc_indexes.py` builds each generated section as rows: a `Table`, a `Note` where a table would be empty, or `Groups`, a heading over several tables (`doc_scripts/view_model.py`). `generated_blocks()` returns them all, in the order the views hold them. The markdown written into a view and the HTML on the site are both formatted from those rows, so what a view says has one source, and the generator's markdown is byte-for-byte what it was before the rows existed.

A cell holds the markdown subset the views use: a link, an inline code span, or bold text, with a `|` escaped. `doc_site/markup.py` renders that subset and refuses anything else (a list, a code fence, a quote, a table, a heading or raw HTML in an introduction) so that a view which gains one fails the build instead of showing wrongly.

## Building the site

From `tools/`:

```sh
python -m doc_site --commit "$(git rev-parse HEAD)" --out /tmp/site
```

`--out` must be empty or absent. The site is `index.html`, one `<view>/index.html` for each view, and `assets/`. A build reads the tree and the commit it is given and nothing else (no clock, no git state, no network), so building twice from one tree and one commit gives the same bytes; a test holds that. `--commit` takes a full commit id; the command looks up that commit's date and hands both to the build. Without it the footer says "Local build".

## The footer

Every page's footer names the commit it was built from, as a link to that commit, with the commit's date in UTC, and credits Simple.css with a link to its licence. GitHub Pages serves a page for up to about ten minutes after a deployment, so a reader who suspects a page is old compares the commit in the footer with `main`. The workflow and the pull request job both pass `"$GITHUB_SHA"`. The licence is served as `assets/simple-licence.txt`, the text of `vendor/simple.LICENSE`, because the vendored stylesheet carries no notice of its own and the licence asks for one with every copy.

## Asset names

`assets/` names each file by the first ten hex digits of its sha256 (`site.3ba5af8963.css`, `simple.fb06245826.css`, `site.eedc88a706.js`) and every page names the file that goes with it, so a cache that holds an old page is never given the new stylesheet, nor a new page the old one. The second matters for `simple.css`: its `integrity` attribute refuses a stylesheet that is not the file the page was built with. The licence keeps its name; a page and a licence that differ cannot break a layout.

Each page takes its `# Title` and introduction from the view's file in [`tools/doc_scripts/view_intros/`](../../../tools/doc_scripts/view_intros) and its sections from the rows. The generator writes the markdown view from the same file and the same rows, so the view and the page say the same. An introduction holds no `##` section: a section written by hand would be dropped from the page, so the build refuses it. The page does not show the introduction as one block. A paragraph that opens with a section's name in bold (`**Roadmap** has one row for each initiative`) is that section's caption and sits under its heading. The first other paragraph is the lede under the title, and the remaining ones (a definition several sections share) are in a "How to read this page" disclosure. The generated markdown view still reads the whole file in order. A paragraph whose section is renamed is not lost: it falls into the disclosure, so rename the bold name with the heading. The links in an introduction are written for the view's place in `docs/`, and the drift checks read them in the generated view.

## Anchors and links

Every heading has the anchor GitHub gives it: lowercase, everything but letters, digits, spaces, hyphens and underscores removed, spaces as hyphens, a repeat numbered `-1`, `-2`. Docs that link to a section of a view therefore reach the same section on the site. A link from one view to another goes to its page, with the anchor kept; a link to any other file goes to it on GitHub.

## The stylesheet

The page is styled with [Simple.css](https://simplecss.org/) (MIT), committed at `tools/doc_site/vendor/simple.min.css`, with its licence beside it. `vendor/simple.pin` names the npm package, the version, the file taken from it, that file's sha256 and the GitHub repository the package is built from. The site makes no request to a third party; nothing is fetched at build time or by a reader's browser.

- A test fails when the committed file's hash differs from the pin.
- `python -m doc_site.vendor --upstream` also compares both with the tarball the npm registry serves for that version, read in memory and never extracted, and with the same file at the repository's `v<version>` tag, so a tarball that differs from the published source fails.
- `python -m doc_site.vendor --update VERSION` replaces the file and the pin together, and writes nothing when the tarball and the tag differ.

The file has no trailing newline, as published, so `end-of-file-fixer` skips `tools/doc_site/vendor/` and the drift check's anchor scan skips `tools/tests/doc_site/`, whose fixtures hold example links to files that exist only in their temp trees.

Renovate moves only the pin's `version` line, because it has no digest for a file inside an npm tarball. The pull request it opens fails the pin test until `--update` has been run with that version, which writes the file and the new hash in one step.

The card layout, the menu drawer and the row filter are `assets/site.css` and `assets/site.js`, which belong to this repository. The page works without JavaScript; the script only adds the filter and the drawer's open button.

## The layout check

```sh
python -m doc_site.layout /tmp/site
```

The check serves a built site on localhost and opens every page in the installed Google Chrome, headless, at 360, 390, 768 and 844 pixels wide and 800 tall (two portrait phones, a small tablet and a wide screen), and at 844 by 390, a phone in landscape. It needs Chrome and `playwright` (a dev dependency), and downloads nothing; the runner image has Chrome. A page fails when it scrolls sideways, when an element ends past the right edge of the screen, when a block holds text wider than the block (a table cell or a card cell that overflows its box), when visible text is under 12 pixels, when a bar that stays on screen (`position: sticky` or `fixed`, a menu drawer aside) takes more than a fifth of the height, or when a link to a heading of the page leaves the heading under such a bar. The header is sticky except on a screen under 30rem tall, where it scrolls away, so that landscape check passes; `html` has a `scroll-padding-top` that keeps a linked heading clear of it. Text hidden for screen readers, such as the table header that the card layout hides, is not on the screen and is not measured. Where the page has a menu button the check also opens the drawer, holds it to the same rules, and fails if the button opens nothing. Every error names the page, the width and the element.

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

A doc links a generated view through its page on the site, `https://wenenhoe.github.io/homelab/<page>/`, with the same `#anchor` it would have used on the file: `project-planning/`, `decision-index/` or `dr-coverage/`. A link to the file's path fails the drift check, and so does a link to a page that does not exist or to an anchor that no heading on the page has ([the check](ci/doc-checks.md)). The anchors are the ones GitHub gives the headings, so a link that worked on the file works on the page. The site is a minute or so behind a merge, so a link to a heading added in the same pull request reaches the page once the deployment has finished, and the drift check, which builds the pages from the tree, accepts it before then.

A table row's details are on the page it names, not behind its own link: the coverage table has no per-app anchors, and a doc that needs one app's row names the app.
