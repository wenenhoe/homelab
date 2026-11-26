---
id: ADR-0119
revision: 0
type: adr
title: "Reading the documentation tree away from GitHub's page"
short: "Docs as site pages"
solution: "Render topic docs, projects and decisions as pages of the doc site with its own renderer extended by a CommonMark library, drawing Mermaid diagrams at build time"
summary: "Where a reader of a topic doc, a project or a decision, on a phone or following a row of a generated view, reads it, and how those pages are made without a second build system or a script the reader must run."
topic: documentation-process
status: superseded
superseded_by: 1
related: [ADR-0117]
relies_on:
  - adr: ADR-0117
    reason: "The deploy job holds no contents write, a page is a function of the tree and the commit it is built from, and the site shows only what the repository holds"
---

# 0119. Reading the documentation tree away from GitHub's page

## Problem

A reader who follows a row of a generated view, or reads on a phone, has to leave the doc site for the markdown file on GitHub, where the page knows nothing of the document's front matter (a decision's state, what supersedes it, which project implements it) and has none of the site's navigation or phone layout. The documents have to be readable where the views are, without a second system to keep and without anything that changes what a document says.

## Decision

The doc site publishes the documentation tree as pages, built by the renderer it already has, extended.

- **Which documents.** Every markdown file under `docs/` except `explorations/` and the `TEMPLATE` files: the topic docs and their index, the project docs, each decision revision, the READMEs and the architecture docs. A page's address follows its path, so a link can be derived from the path it already uses.
- **How a body is read.** A CommonMark library reads the body, with tables, strikethrough and task-list boxes, and the existing templates and styles lay it out. A block the renderer has no rule for fails the build, as markup outside its subset fails a view today, so a page is never wrong without saying so. Headings take GitHub's anchors.
- **What a page adds.** A header drawn from the front matter: a decision's state and what it supersedes, replaces or relies on, the projects that implement it; a project's status, blocker and decision. Every page links to its source on GitHub.
- **Links.** A relative link to a document the site renders becomes a link to its page with its anchor kept; a link to any other file in the repository goes to it on GitHub, as it does today; a link to a view goes to its page.
- **Diagrams.** A Mermaid block is drawn to SVG during the build in headless Chrome, from a bundle committed and pinned as the stylesheet is, in a light and a dark rendering that the page chooses between by `prefers-color-scheme`. No script reaches the reader. A diagram that fails to render fails the build.
- **Navigation.** The site gains Topics, Projects, Decisions and Architecture alongside the three views, which keep the build that makes them and their card layout on a phone. A generated view's rows link to the pages. The home page carries `docs/README.md`, and each section opens on its list, with its README one link away from every page of the section.
- **Reading aids.** A decision page links every revision of its lineage and the neighbouring ADRs by number, and a page's prose has one reading measure. The decision index may lay its rows out for finding a decision, with its numbers ten to a row and its topic groups as tabs, in the markdown view and on the site, provided every row's content stays in the view, a group stays reachable by its anchor and by the filter, and every group shows when the stylesheet is not applied. A document page with several headings lists them on the page, beside the prose on a wide screen and above it on a phone, and the index of topics shows its groups as tabs on the site with a filter over its links, on the same terms. These aids are made from a page's own headings and links, so no source document carries markup for them, and they hide nothing from a reader without the stylesheet.

```mermaid
flowchart LR
    tree["docs/ in the tree"] --> body["body: CommonMark library"]
    tree --> fm["front matter"]
    tree --> mm["Mermaid blocks"]
    mm --> chrome["headless Chrome, pinned bundle"]
    chrome --> svg["light and dark SVG"]
    body --> page["page"]
    fm --> page
    svg --> page
    views["generated view rows"] --> link["links to pages"]
    page --> site["site artifact"]
    link --> site
```

The diagram shows the design as this revision decided it, not what runs now.

## Invariants

- A page is a function of the tree and the commit it is built from: it reads no history and no clock, and two builds of one commit are the same bytes.
- The site shows only what the repository holds, and the public-repository rule in [`docs/README.md`](../../README.md#public-repo) applies to every page.
- Markup the renderer does not handle fails the build and is never shown wrongly.
- Every heading has the anchor GitHub gives it, so a link that worked on the file works on the page.
- The reader's browser runs no script that a page needs to be read, and makes no request to a third party.
- Every page links to its source file.
- The deploy job holds no `contents` write permission and deploys only from `main`.
- An exploration is never a page.

## Non-goals

- Searching across the documents. [ADR 0117](../0117-delivering-the-generated-doc-views-to-readers/revision-000.md) names it as a non-goal and this revision keeps it so.
- Editing or commenting on a page, or any behaviour that needs a server.
- A view of an older commit or of a pull request.
- Documents outside `docs/`, such as the READMEs at the repository root.

## Reconsideration triggers

- The renderer refuses documents often enough that authors write around it.
- A pinned bundle's update or the Mermaid version GitHub draws with differ enough that a diagram reads differently.
- The site approaches its size limit, or the build approaches the deployment timeout.
- A documentation generator that checks links and anchors strictly, builds the same bytes twice and takes the generated views in, so that a second build costs less than keeping this renderer.
- A reader asks for search that the site cannot give.
