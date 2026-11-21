---
id: EXP-doc-site-reach
title: "How much of the documentation should the doc site render, and with what?"
type: exploration
status: open
summary: "Whether topic docs, projects and decisions should be pages on the doc site rather than links to GitHub, in what order, and whether the renderer grows from the one the three views use or is replaced by a documentation generator."
topic: documentation-process
related: [ADR-0117]
---

# How much of the documentation should the doc site render, and with what?

The site renders the three generated views and nothing else, so every row on them (a project, a decision) links out to its markdown file on GitHub. [ADR 0117 (Generated doc views)](../decisions/0117-delivering-the-generated-doc-views-to-readers/revision-000.md) lists topic docs, decisions and projects as non-goals, and rendering them reverses that. The question is whether a reader gains enough from staying on the site, on a phone especially, to pay for a renderer that handles all of a document and for the checks that go with it.

## What bears on it

- **What is there to render.** 105 topic docs, 34 project docs and 101 decision lineages in 128 revision files, plus the architecture diagrams. The topic docs hold about 150 fenced blocks and about 170 table rows; 44 docs hold 48 Mermaid diagrams.
- **What the renderer handles now.** [`markup.py`](../../tools/doc_site/markup.py) renders a link, an inline code span and bold text, and refuses a list, a fence, a quote, a table, a heading or raw HTML, so a view that gains one fails the build. A page for a topic doc needs all of those. The refusal is the property that keeps the three views honest, and a fuller renderer would have to keep a version of it.
- **What a reader has on GitHub.** GitHub renders markdown, tables and Mermaid, and searches the repository. What it does not give is a page that knows a document's front matter (a decision's state, what supersedes it, which project implements it), navigation between kinds of document, or the layout the site already has for a phone.
- **Links and anchors are checked.** A doc links another by relative path, and the drift check holds every anchor to the one GitHub gives a heading ([`doc-site.md`](../topics/engineering/doc-site.md#anchors-and-links)). A site page for each document would map those paths to pages and keep the same anchors, and a link to a file the site does not render would still go to GitHub.
- **Exploration pages would be durable links.** Nothing durable may point at an exploration because it is deleted when it ends, so they are left off the site, or the site's links to them are the one exception.
- **Mermaid.** The check that renders diagrams needs Docker ([`checks-without-docker.md`](../topics/engineering/checks-without-docker.md)). The site makes no request to a third party, so a diagram library in the page would have to be vendored and pinned as the stylesheet is. The runner has Chrome, which could render each diagram to SVG at build time.
- **Searching** across the repository is a non-goal of ADR 0117 as written, with "anything that needs a server". A search index built at deploy and read in the page needs no server, but the non-goal names search.
- **Limits.** A Pages site is limited to 1 GB and a deployment times out after 10 minutes. About 270 pages of prose is small against both.
- **The generator market.** Material for MkDocs entered maintenance mode and its stated window for fixes has ended; Zensical, from the same maintainers, is its successor and is meant to read the same configuration. Whether it supports what this repo needs (strict link checking, a build that is the same bytes twice, hooks to pass in the three generated views) has not been checked. Neither Starlight, mdBook nor Hugo has been compared.
- **Two systems.** The three views are cards built from rows, and a generic generator cannot produce them. Adopting one means keeping both builds and giving them one navigation and one footer.

Still to find out: how many of the 150 fenced blocks and the tables a CommonMark library renders the way GitHub does, and whether any document uses markup it does not.

## Options

- **Stay as it is.** The views keep linking to GitHub. No new code, and the topic docs are read where GitHub already renders them. The phone experience and the jumps between the site and GitHub stay as they are.
- **Pages from front matter only.** A page for each project and decision, built from its front matter (status, summary, what it implements or replaces) with a link to the full text on GitHub. The renderer stays small, and the views link to pages that carry what the row cannot. A reader still leaves for the body.
- **Grow the renderer with a CommonMark library.** Topic docs, then projects, then decisions, through a Python library, with the existing templates, the same anchors, the layout check and the byte-for-byte test. Costs a library to pin and keep, a refusal rule for markup it does not handle, link rewriting, a decision on Mermaid, and a layout check that scales to more pages. Keeps one build and one footer.
- **A documentation generator for the prose docs**, with the three views kept as they are and joined by one navigation. Gets search, navigation and themes without writing them. Costs a second build, a dependency whose direction is unsettled, and a theme to bring in line with the views.

Either of the last two also has to settle: whether a decision gets a page for each revision or for each lineage, how a superseded revision is shown, and whether Mermaid is rendered ahead of time or in the page.

## Leaning

Pages from front matter first, since the views link out most often to projects and decisions and it needs no new markdown support. Then the CommonMark route for topic docs, with Mermaid rendered at build time, once a check has shown the library reads the repo's own documents without a refusal. A generator is worth a second look if search turns out to be the thing readers lack. What would change this: the library failing on a share of the documents, or a request for search that the site cannot meet.
