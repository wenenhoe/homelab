# The doc site renderer

`tools/doc_site` turns the three generated views ([`project-planning.md`](../../project-planning.md), [`decision-index.md`](../../decision-index.md) and [`coverage.md`](../disaster-recovery/coverage.md)) into a small static site. Its design is [ADR 0117](../../decisions/0117-generated-doc-views/), and the plan for getting the site published is [`views-site.md`](../../projects/views-site.md). Until that plan finishes, the views stay committed and this renderer only builds the site on request.

## One set of rows, two outputs

`doc_scripts/generate_doc_indexes.py` builds each generated section as rows: a `Table`, a `Note` where a table would be empty, or `Groups`, a heading over several tables (`doc_scripts/view_model.py`). `generated_blocks()` returns them all, in the order the views hold them. The markdown written into a view and the HTML on the site are both formatted from those rows, so what a view says has one source, and the generator's markdown is byte-for-byte what it was before the rows existed.

A cell holds the markdown subset the views use: a link, an inline code span, or bold text, with a `|` escaped. `doc_site/markup.py` renders that subset and refuses anything else (a list, a code fence, a quote, a table, a heading or raw HTML in an introduction) so that a view which gains one fails the build instead of showing wrongly.

## Building the site

From `tools/`:

```sh
python -m doc_site --out /tmp/site
```

`--out` must be empty or absent. The site is `index.html`, one `<view>/index.html` for each view, and `assets/`. A build reads the tree and nothing else (no clock, no commit, no network), so building twice gives the same bytes; a test holds that.

Each page takes its `# Title` and introduction from the committed view file and its sections from the rows. A hand-written `##` section in a view is not carried to the site; the views hold generated sections only.

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
