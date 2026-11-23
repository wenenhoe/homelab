---
id: EXP-question-slug         # EXP- and the file name without .md
title: "The question, without naming a solution"
type: exploration
status: open
summary: "One line on what is being weighed; feeds the generated planning view"
topic: deployment-platform    # one of TOPICS in tools/doc_scripts/doc_frontmatter.py
# related: [ADR-NNNN]         # decision lineages this bears on
---

# The question

What has to be decided, in a sentence or two, and why it cannot be answered
yet.

## What bears on it

Facts a reader needs, without narration of how they were found. Name what
still has to be checked.

## Options

Each option and what it would cost or risk. Keep the ones that lost, with the
reason, since they move to the decision's Alternatives.

## A new system

Only when the question adds a system. Where it runs and why that zone; the
flows in and out, as `flows.yaml` entries; the shared services it uses or
provides; what it adds to the node's memory and cores; and what reaches it.

## Leaning

Optional. Where this is heading and what would change it.
