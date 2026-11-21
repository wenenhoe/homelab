---
id: ADR-0117
revision: 0
type: adr
title: Delivering the generated documentation views to readers
short: Generated doc views
solution: Publish the three views as a site on GitHub Pages from every push to main, stop committing them, and generate them locally in a checkout
summary: How the decision index, the planning view and the disaster-recovery coverage table reach the people who read them on GitHub, on a phone and in a checkout, without every change having to commit them.
topic: documentation-process
status: accepted
related: [ADR-0037, ADR-0095, ADR-0112]
---

# 0117. Delivering the generated documentation views to readers

## Problem

Three views are generated from the tree: the decision index, the planning view and the disaster-recovery coverage table. They are read on GitHub, including on a phone, and from a checkout, by the maintainer and by agents. A reader has to find each one current, and a reader on a phone has to be able to read it. Keeping them current must not make two unrelated changes conflict, or need machinery that runs on every patch, or tie a rebuilt change to the history it was first built from.

## Context

- **What committing cost.** The `generate-doc-indexes` hook rewrote the views and failed when it had to, so every commit carried views that matched the generator. Patches left them out so two series did not conflict on them, and the landing tool needed apply hooks, a reset between layers and one patch per `git am` to produce them. Two changes that each add a decision still edited the same table, and GitHub refuses to merge a conflicting pull request. A workflow cannot push a regenerated view to `main`, which accepts only a pull request merged with the Admin bypass ([`branching.md`](../../topics/engineering/branching.md#the-rulesets)). 59 of the 200 newest merged pull requests when counted changed a view.
- **The views read only the tree.** Each view is a function of the tree, so a rebuilt layer has the same views as its first build and the generator needs no history.
- **Who reads them.** They are read on GitHub, on a phone and from a checkout. Some 60 docs linked the decision index and the planning view by path, 3 of them inside decision revisions, and the drift check accepts a link to a site URL. A markdown table of four or five columns with long cells is readable on a phone only by scrolling sideways.
- **What publishing to Pages takes.** The deploy job needs `pages: write` and `id-token: write` in the `github-pages` environment and no `contents: write`, so it cannot change a branch or a tag. The Pages source is set to GitHub Actions by hand, and the environment can be limited to `main`, which refuses a deployment from another branch. A site is limited to 1 GB, a deployment times out after 10 minutes, and the soft bandwidth limit is 100 GB a month.
- **A workflow on every push to `main`** with a concurrency group and `cancel-in-progress: false` has at most one run going and one waiting, and a burst of merges ends with a run on the newest commit.
- **The write token.** [ADR 0095 (Progress log)](../0095-recording-what-was-worked-on-each-week-and-month/revision-000.md) describes the progress log's publish job as the one job with a write token, a `contents: write` that pushes to its own branch. The deploy job writes a deployment, not a ref, so that record stays true.
- **A page for a phone.** Plain CSS with stacked cards under a breakpoint did not scroll sideways at 360 to 768 px in portrait, but in landscape at about 844 px cards that began below 40rem and `overflow-wrap:anywhere` on cells broke words mid-word. A scroll-width and font-size check did not see this and reading the page on a phone did, so the breakpoint for cards is about 62rem and a cell does not break inside a word.
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

- A renderer, with tests, is a second format to keep in step with what a view says.
- Nothing on `main` links a view by path: a doc links the site, and the drift check fails a doc that links a view by its path.
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
- Changing how a series lands: removing the conflicts makes parallel landing possible without deciding it ([ADR 0112](../0112-landing-a-series-of-dependent-changes-on-main/revision-002.md) lists it as a non-goal).

## Validation

A test builds each page twice from a fixture tree and fails when the bytes differ. The workflow tests fail a `contents: write` on the deploy job. The drift check fails a doc that links a view by a path that no longer exists. The layout check runs at portrait and landscape phone widths and fails a page that scrolls sideways or a cell that breaks inside a word.

## Reconsideration triggers

- The site grows toward its size limit or its bandwidth limit, or deployments approach the timeout.
- The repository becomes private, or holds anything the views should not show, so that a public site is no longer harmless.
- The renderer costs more to keep than the conflicts it removed.
- GitHub changes how a workflow deploys to Pages, or the permissions it needs.
