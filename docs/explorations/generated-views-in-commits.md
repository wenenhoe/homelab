---
id: EXP-generated-views-in-commits
title: "Do the generated doc views need to be committed with every change?"
type: exploration
status: open
summary: "Whether the three generated views must be committed in each pull request, given that they are the files two unrelated changes most often both rewrite and that the apply hooks and the patch rules exist only to produce them."
topic: documentation-process
related: [ADR-0112]
---

# Do the generated doc views need to be committed with every change?

The decision index, the planning view and the disaster-recovery coverage table are generated from frontmatter and the app catalog, and each is committed. Every change that adds or moves a decision, a project, an exploration or an app has to commit the regenerated view with it. That cost shows up in three places: the tooling around `git am`, two changes that cannot land side by side, and a rebuilt commit that is not identical to the first build. The question is whether committing them is worth that.

## What bears on it

- [`.githooks/generated-views`](../../.githooks/generated-views) lists the three views. The `generate-doc-indexes` hook rewrites them and fails when it had to, so every commit carries views that match the generator ([`pre-commit.md`](../topics/engineering/pre-commit.md#applying-patches-with-git-am)).
- Patches leave the views out so two series that each add a project or a decision do not conflict on them. `pre-applypatch` regenerates and stages them, `post-applypatch` amends them into the commit, and the replay resets them between layers and applies one patch per `git am` ([ADR 0112 (Landing a patch series)](../decisions/0112-landing-a-series-of-dependent-changes-on-main/revision-001.md)). A plain `git am` of a series that edits one of them stops at the next patch.
- Of the 200 newest merged pull requests, 59 changed at least one view: the planning view in 52, the decision index in 37 and the coverage table in 1. Two changes that add a decision both edit the same table, so a merge of the second can conflict even though the changes share no other file. GitHub's merge refuses a conflicting pull request, and a workflow cannot push a regenerated view to `main`, which accepts only a pull request merged with the Admin bypass.
- The planning view's table of explorations gives each one's date, taken from its newest commit, and a change not yet committed counts as today. A replayed layer that adds or edits an exploration therefore carries the date of the replay, and [`kept.py`](../../tools/land_series/kept.py) records the patches a branch was built from because a rebuilt commit differs from the kept one.
- The decision index and the planning view are read on GitHub and linked by anchor from the README, `AGENTS.md` and the docs. The project scope rule and the progress log's classifier also name them by path.

## Options

- **Keep them committed as they are.** Nothing to change. The conflicts, the hook machinery and the date difference stay, and a parallel landing of layers that touch the same view stays impossible.
- **Make a build reproducible.** The generator would date an exploration from the layer's own author date, not the date of the replay, so two replays of a layer give the same commit. It does not touch conflicts. It depends on the apply hooks being given the patch's date, which has to be checked.
- **Compare trees without the views.** A scheme that keys a result on a tree, such as reusing a proof of a layer, would leave the three paths out of the key. Heavy checks read none of them. Replays and landed layers may then differ in the views alone. Conflicts remain.
- **Stop committing them.** The views are produced when read, by running the generator locally, and CI publishes a copy. The two apply hooks, the patch rule, the reset between layers, the date difference and the conflicts all go. Readers on GitHub lose the rendered pages and the anchors that point into them unless a published copy replaces them, and `main` cannot take a bot's commit of the views, so the copy lives outside the repository. It changes what a doc may link to, which is a decision, not a tidy-up.
- **Split each view by entry.** A decision or project would add its own row file, so no two changes share one. The views are one page meant to be scanned, which a directory of rows is not.
- **Regenerate at landing.** The tool would rebase a conflicting layer and run the generator before merging. It makes a new commit and a new tree each time, so any result keyed on the layer's tree is lost unless the views are left out of the key.

## Leaning

None yet. Making a build reproducible and leaving the views out of a key are small and help only the landing question. Not committing them removes the most machinery, and its cost falls on how the views are read, which has to be settled first: whether they are read on GitHub or from a checkout, and by what.

## What has to be checked first

- What the apply hooks are given of the patch's date.
- Whether anything besides the `generate-doc-indexes` hook checks that a committed view is current.
- How the scope rule and the progress log's classifier use the views' paths.
- How the maintainer and the agents read the views.
