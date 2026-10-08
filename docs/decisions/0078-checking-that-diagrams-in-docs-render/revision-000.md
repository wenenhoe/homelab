---
id: ADR-0078
revision: 0
type: adr
title: Checking that diagrams in docs render
short: Diagram render check
solution: "Leaning: a pre-commit hook that parses every Mermaid block with Mermaid's own parser in Node, with no browser, its outcome decided by unit-tested Python"
summary: How a Mermaid diagram that does not parse is stopped before it merges, given that the docs checks read markdown as text and nothing in CI renders a diagram.
topic: documentation-process
status: working
related: [ADR-0028, ADR-0064]
---

# 0078. Checking that diagrams in docs render

## Problem

A Mermaid diagram with a syntax error reaches `main` without anything failing. On GitHub it shows as an error box where the picture should be, and only a reader who opens the page sees it.

What has to be true: a diagram that does not parse fails a check before it merges; the check needs no browser on the machines that run it; and the logic that decides the outcome is tested like the repo's other checks.

## Context

Mermaid blocks appear in `docs/architecture/`, in topic docs, and, since [`docs/decisions/README.md#diagrams-and-tables`](../README.md#diagrams-and-tables), in decision records. Today the repo has 24, all `flowchart` or `sequenceDiagram`.

`check_doc_drift.py`, the index generator and markdownlint read markdown as text, so a malformed block passes all three. The decisions README asks for a manual render with `mmdc` before merging and says no CI check does it.

CI runs one `pre-commit` invocation in the `pre-commit-checks` job, which carries every commit-stage hook. The repo has no `package.json`; Node tooling arrives as pre-commit hook environments.

[ADR 0064 (CI and doc check code)](../0064-where-the-code-behind-ci-and-documentation-checks-lives/revision-000.md) puts code that decides a check's outcome in unit-tested Python under `tools/`.

Mermaid has no Python parser. Its own parser runs in Node under jsdom with no browser. It accepts every block the repo has today and rejects a malformed one with the line it stopped on. Rendering with `mermaid-cli` needs a headless Chromium.

Parsing is not rendering. The parser does not lay a diagram out, so a diagram can parse and still read badly, and GitHub draws with its own Mermaid version.

## Decision

Leaning: a `check-mermaid` hook in the existing `pre-commit-checks` run.

- A Python module under `tools/doc_scripts/` finds every fenced `mermaid` block in the repo's tracked markdown, hands each to a Node parser, and fails with the file, the block's first line and the parser's message.
- The parser is a short Node script that loads Mermaid under jsdom and calls `mermaid.parse` on the diagram it is given. It writes the error to stderr and exits non-zero when the diagram does not parse.
- `mermaid` and `jsdom` are pinned to exact versions.
- Layout stays a manual `mmdc` render, as the decisions README says now.

## Alternatives considered

- **Render in CI with `mermaid-cli`.** It would catch what only a browser rejects, but it needs a headless Chromium wherever the hook runs, on every machine that runs `pre-commit` as well as in CI, for a failure the parser already catches.
- **The manual `mmdc` render alone.** It is the rule today. Nothing fails when it is skipped, so a slip merges.
- **GitHub's own rendering.** It shows the error to a reader after the fact and gates nothing.
- **A Node-only hook that also finds the blocks.** One fewer moving part, but the logic that decides the outcome would be untested JavaScript, against ADR 0064.

## Assumptions

- **Claim:** The `pre-commit-checks` run can provide Node and the two pinned packages to a hook whose outcome logic is Python.
  **Breaks if wrong:** The hook is Node-only, with its outcome logic outside ADR 0064's rule, or it becomes a CI job of its own.
  **Checked by:** a spike of the hook in the `pre-commit-checks` job.

## Consequences

- Node and two npm packages join the pre-commit environment, and a Mermaid upgrade can change what parses.
- A diagram can pass the check and still be hard to read, or fail on GitHub's Mermaid version, so the manual render stays for layout.
- The decisions README's rule about rendering changes when this is implemented, and [`doc-checks.md`](../../topics/engineering/ci/doc-checks.md) gains the check.

## Invariants

- A Mermaid block that does not parse under the pinned parser does not merge.
- The check reads markdown and changes nothing.

## Non-goals

- Whether a diagram is legible, or whether it matches its Decision.
- Diagram types the pinned parser does not accept.

## Validation

- Unit tests cover finding blocks in a file, including fences inside other fences, and reporting a failure, with the Node parser replaced by a double bound to its real interface ([ADR 0070 (Test doubles binding)](../0070-what-a-unit-tests-doubles-are-bound-to/revision-000.md)).
- The hook runs over every Mermaid block in the repo on each pull request.

## Reconsideration triggers

- A diagram the pinned parser accepts that GitHub refuses to draw.
- Mermaid dropping support for parsing under jsdom.
