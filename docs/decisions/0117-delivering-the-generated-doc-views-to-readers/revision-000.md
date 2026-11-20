---
id: ADR-0117
revision: 0
type: adr
title: Delivering the generated documentation views to readers
short: Generated doc views
solution: Publish the three views as a site on GitHub Pages from every push to main, stop committing them, and generate them locally in a checkout
summary: How the decision index, the planning view and the disaster-recovery coverage table reach the people who read them on GitHub, on a phone and in a checkout, without every change having to commit them.
topic: documentation-process
status: working
related: [ADR-0037, ADR-0095, ADR-0112]
---

# 0117. Delivering the generated documentation views to readers

## Problem

Three views are generated from the tree: the decision index, the planning view and the disaster-recovery coverage table. They are read on GitHub, including on a phone, and from a checkout, by the maintainer and by agents. A reader has to find each one current, and a reader on a phone has to be able to read it. Keeping them current must not make two unrelated changes conflict, or need machinery that runs on every patch, or tie a rebuilt change to the history it was first built from.

## Context

- **What committing costs.** The `generate-doc-indexes` hook rewrites the views and fails when it had to, so every commit carries views that match the generator. Patches leave them out so two series do not conflict on them, and `pre-applypatch`, `post-applypatch`, a reset between layers and one patch per `git am` exist to produce them ([ADR 0112 (Landing a patch series)](../0112-landing-a-series-of-dependent-changes-on-main/revision-001.md)). A plain `git am` of a series that edits one stops at the next patch.
- **How often.** Of the 200 newest merged pull requests when counted, 59 changed at least one view: the planning view in 52, the decision index in 37 and the coverage table in 1. Two changes that add a decision both edit the same table, so the second can conflict although they share no other file. GitHub refuses to merge a conflicting pull request, and a workflow cannot push a regenerated view to `main`, which accepts only a pull request merged with the Admin bypass ([`branching.md`](../../topics/engineering/branching.md#the-rulesets)).
- **The views read only the tree.** The planning view lists an exploration by name and question and shows no date, so each view is a function of the tree: a rebuilt layer has the same views as its first build, and the generator needs no history.
- **Who reads them, and how.** The views are read on GitHub, on a phone and from a checkout. The decision index and the planning view are linked by path from 60 docs, 68 links in all, 3 of them inside decision revisions: 16 anchor links into the index, 12 into the planning view, and 27 to the coverage table with no anchor. The drift check accepts a link to a site URL. The project scope rule (`doc_scope.py`), the progress log's classifier (`classify.py`), the generator's wiring and `merge_adr_links.py` also name the views by path, and `check_doc_drift.py` reads the committed index and planning view, so it has to generate or check them in place once they are not committed. A markdown table of four or five columns with long cells is cramped on a phone and readable there only by scrolling sideways.
- **What publishing to Pages takes.** The deploy job needs `pages: write` and `id-token: write`, runs in the `github-pages` environment, and needs the repository's Pages source set to GitHub Actions by hand. It needs no `contents: write`, so it cannot change a branch or a tag. A trial in a scratch repository showed that the source can be set to GitHub Actions, that the `github-pages` environment can be limited to `main` and then refused a deployment from another branch, and that `zizmor` reports only `unpinned-uses` on the job, which pinning the actions by commit removes. The repository has no Pages site and no environment yet. A published site may be at most 1 GB, a deployment times out after 10 minutes, the site has a soft limit of 100 GB of bandwidth a month, and the soft limit of 10 builds an hour does not apply to a custom workflow.
- **A workflow on every push to `main`** with a concurrency group and `cancel-in-progress: false` has at most one run going and one waiting, and GitHub replaces a waiting run with a newer one, so a burst of merges ends with a run on the newest commit. `warm-caches.yml` is built this way.
- **The write token today.** [ADR 0095 (Progress log)](../0095-recording-what-was-worked-on-each-week-and-month/revision-000.md) describes the progress log's publish job as the one job with a write token: a `contents: write` that pushes to its own branch. The deploy job has a smaller reach: it writes a deployment, not a ref, and its permissions are its workflow's own, so the record's wording stays true with no new revision of it. The header comment of `progress-log.yml`, which calls the progress log the only `contents: write`, is reworded when the deploy workflow lands.
- **A page for a phone.** A static page with no framework, plain CSS, `system-ui` fonts, stacked cards under a breakpoint and a dark mode set by `prefers-color-scheme` did not scroll sideways at 360 to 768 px in portrait. In landscape on a phone, at about 844 px, a card layout that started below 40rem and a `overflow-wrap:anywhere` on table cells gave narrow columns whose words broke mid-word. A scroll-width, font-size and touch-target check did not see this, and reading the page on a phone did. The breakpoint for cards has to be about 62rem, and table cells must not break inside a word.
- **Public content.** The repository is public and the views hold nothing it does not, so a public site shows no more than the views already do.

## Decision

A workflow on every push to `main` builds the three views as static pages and deploys them to GitHub Pages. The pages are made for the reader's viewport: a table that is wide on a desktop becomes stacked cards on a narrow screen, every section has a stable URL, and the planning view and the decision index can be filtered by status and topic. The pages are produced by the generator from the same data as today, so there is one source for what a view says.

The views stop being committed. The files, the apply hooks, the patch rule, the reset between layers and the one-patch-per-`git am` rule go, and so do the conflicts. A checkout runs the generator (by hand, or from `post-merge` and `post-checkout` hooks) and gets the views as ignored files, so an agent that clones the repository and runs one command reads the same content as the site.

The change is made in two steps, so no reader loses a view. First the site is published while the views are still committed. Once the site is trusted, the views stop being committed and the docs that linked them point to the site.

The deploy job holds `pages: write` and `id-token: write` and no `contents: write`, runs only for `main`, and uses a concurrency group with `cancel-in-progress: false`.

## Alternatives considered

- **Keep them committed.** Nothing to change, and the conflicts, the hook machinery and the phone-sized tables all stay.
- **Compare trees without the views.** A scheme that keys a result on a tree could leave the three paths out of the key, since heavy checks read none of them. It helps the landing question only; the conflicts and the phone remain.
- **Local only.** Gitignored views regenerated by hooks remove the machinery, but a reader on GitHub or a phone loses the rendered views and the anchors into them. It stays as the way a checkout gets them.
- **A generated branch**, regenerated on every push to `main` the way the progress log is. The views stay rendered on GitHub, but it needs a second job with `contents: write`, a ruleset for the branch made by hand, and a lag, and the tables are the same cramped tables on a phone. A site gives a smaller token and a layout made for a phone.
- **Split each view by entry**, so no two changes share one. The views are one page meant to be scanned, which a directory of rows is not.
- **Regenerate at landing**, by rebasing a conflicting layer and running the generator before it merges. It makes a new commit and a new tree each time, so a result keyed on the layer's tree is lost, and it leaves the phone as it is.

## Consequences

- The conflicts on the views, the apply hooks, the patch rule, the reset between layers and the difference between a kept commit and a rebuilt one go once the views stop being committed. The parts of [ADR 0112](../0112-landing-a-series-of-dependent-changes-on-main/revision-001.md) that describe them need a new revision when this one is accepted.
- A renderer, with tests, is a second format to keep in step with what a view says, and a design to maintain.
- Nothing on `main` links a view by path. The 65 links outside decision revisions point to the site or go, which changes what a doc may link to; the 3 inside revisions are edited as editorial.
- `check_doc_drift.py`, `doc_scope.py`, `classify.py`, the generator's wiring and `merge_adr_links.py` change to read or name the views without a committed file, and the two tests of the apply hooks that list the views go with the hooks.
- The site is a minute or so behind a merge, and a checkout has to run the generator to read a view.
- The repository's Pages setting is made by hand, like the rulesets, and is not in the repository.

## Invariants

- The deploy job has no `contents: write`, so it cannot change a branch or a tag, and it deploys only from `main`.
- A view is a function of the tree at the commit it is built from: it reads no history and no clock, so two builds of one commit are the same.
- The site shows only what the repository holds, and the public-repository rule in [`docs/README.md`](../../README.md#public-repo) applies to it as to any doc.
- Every reader has a view: GitHub and the phone read the site, and a checkout generates it.
- The generator is the one source of a view's content, for the site and for a checkout alike.

## Non-goals

- A documentation site in general. The topic docs, the decisions and the projects stay markdown files on GitHub.
- Searching across the repository, or anything that needs a server.
- Changing how a series lands: removing the conflicts makes parallel landing possible without deciding it ([ADR 0112](../0112-landing-a-series-of-dependent-changes-on-main/revision-001.md) lists it as a non-goal).

## Validation

A test renders each view from a fixture tree and fails when the three differ between two builds of the same tree. The deploy job's permissions are read by the workflow tests, which fail a `contents: write` on it. The drift check fails a doc that links a view by a path that no longer exists. The renderer's layout is checked at portrait and landscape phone widths, and fails a page that scrolls sideways or a table cell that breaks inside a word.

## Reconsideration triggers

- The site grows toward its size limit or its bandwidth limit, or deployments approach the timeout.
- The repository becomes private, or holds anything the views should not show, so that a public site is no longer harmless.
- The renderer costs more to keep than the conflicts it removed.
- GitHub changes how a workflow deploys to Pages, or the permissions it needs.
