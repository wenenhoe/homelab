---
id: ADR-NNNN                 # the lineage: one per problem, identical in every revision
revision: 0                  # the generation; matches revision-NNN.md
type: adr
title: "The problem, stated without naming a solution"   # identical in every revision
short: "The problem in a few words"   # one line, at most 40 characters, unique across lineages
solution: "This revision's answer, in one line"
summary: "One line on what the problem covers; feeds the generated index"
topic: repository-tooling    # one of TOPICS in tools/doc_scripts/doc_frontmatter.py
status: working              # working | approved | accepted | superseded | abandoned | retired
weight: light                # a light record: no Invariants, Non-goals or Validation, and a short body
# supersedes: 0
# related: [ADR-NNNN]
---

# NNNN. Problem title

For a decision that touches no trust boundary, credential or recovery path
and takes one pull request to reverse. Anything bigger uses
[`TEMPLATE.md`](TEMPLATE.md); anything the code already makes obvious is a
topic doc or a convention, not a decision. Keep the body under the length
that `doc_graph.py` allows.

## Problem

What has to be true, independent of any solution.

## Context

The facts that decide it, in a few lines.

## Decision

The solution, stated plainly.

## Alternatives considered

The option that lost and the reason it did.

## Reconsideration triggers

What would reopen it.
