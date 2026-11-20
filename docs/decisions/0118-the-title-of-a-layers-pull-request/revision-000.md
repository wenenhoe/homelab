---
id: ADR-0118
revision: 0
type: adr
title: The title of a layer's pull request
short: Layer pull request title
solution: The series file may name a layer's title on a manifest comment line, and a layer without one keeps its first commit's subject
summary: What a layer's pull request is called when its commits have to be written in dependency order, so that the first commit does not always say what the layer is for.
topic: repository-tooling
status: accepted
weight: light
narrows: ADR-0112
---

# 0118. The title of a layer's pull request

## Problem

A layer's pull request title is the one line `main`'s history keeps for the change: it becomes the merge commit's body. It has to say what the whole layer is for, whatever order the commits are written in.

## Context

- [`land_series`](../../../tools/land_series) takes the title from the layer's first commit ([ADR 0112](../0112-landing-a-series-of-dependent-changes-on-main/revision-001.md)). The commits of a layer are in dependency order, so the first is often a preparation (a refactor, a data file, a widening) or the first of several steps, and its subject names that step and not the layer.
- Ordering the commits so that the best subject comes first fights the dependency order, and a preparatory subject that is stretched to name the layer runs past the 72 characters a subject may have ([`conventions.md`](../../topics/engineering/conventions.md#commits)).
- A series file already carries per-file choices as manifest comment lines, such as `# base: develop` ([`landing-a-series.md`](../../topics/engineering/landing-a-series.md#the-input)), so a choice made while writing the series travels with the file the maintainer reviews.

## Decision

A manifest comment line `# title <number>: <subject>` names the title of the pull request with that number. A layer with no such line keeps its first commit's subject, so a series written before this is unchanged.

The title is a subject in the form every subject has: Conventional Commits, imperative, lowercase after the colon, at most 72 characters. The tool refuses a title that is not, a number the manifest does not list, and a number given two titles. The title changes only the pull request's title and the merge commit's body: the commits and the branch are the same, so a kept branch stays valid when a title changes, and a pull request already open for the branch takes the new title.

## Alternatives considered

- **Keep the first commit's subject and order the commits to suit it.** The title then depends on dependency order, which a preparatory commit settles against it.
- **A title on every manifest line.** A line is a patch id and a slug; a subject holds spaces and a colon, and it would be repeated for each commit of a layer.
- **A commit that carries only the title.** It puts an empty commit into `main`'s history.
- **Editing the title on GitHub.** The title the maintainer reviewed in the series file is not the one merged, and a replay of the file forgets the edit.

## Reconsideration triggers

- Most multi-commit layers need a title line, so the title should come from the layer and not from its first commit.
- A title line and its layer's commits drift apart often enough that the tool should compare them.
