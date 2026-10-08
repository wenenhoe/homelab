---
id: ADR-0078
revision: 0
type: adr
title: Checking that diagrams in docs render
short: Diagram render check
solution: "Render every Mermaid block with the pinned mermaid-cli container image in a CI job that runs when markdown changes, its outcome decided by unit-tested Python"
summary: How a Mermaid diagram that does not render is stopped before it merges, given that the docs checks read markdown as text and nothing in CI renders a diagram.
topic: documentation-process
status: accepted
related: [ADR-0028, ADR-0064]
---

# 0078. Checking that diagrams in docs render

## Problem

A Mermaid diagram with a syntax error reaches `main` without anything failing. On GitHub it shows as an error box where the picture should be, and only a reader who opens the page sees it.

What has to be true: a diagram that does not render fails a check before it merges; the check needs no Node or browser installed on the machines that run it; and the logic that decides the outcome is tested like the repo's other checks.

## Context

Mermaid blocks appear in `docs/architecture/`, in topic docs, and, since [`docs/decisions/README.md#diagrams-and-tables`](../README.md#diagrams-and-tables), in decision records. All are `flowchart` or `sequenceDiagram`.

`check_doc_drift.py`, the index generator and markdownlint read markdown as text, so a malformed block passes all three. The decisions README asks for a manual render with `mmdc` before merging and says no CI check does it.

CI's `pre-commit-checks` job runs every commit-stage hook over every file on every pull request. A check that is heavier, or that matters only for some changes, runs as a job of its own that `detect-changes` scopes, as `ansible-lint` and `release-checksums` do.

[ADR 0064 (CI and doc check code)](../0064-where-the-code-behind-ci-and-documentation-checks-lives/revision-000.md) puts code that decides a check's outcome in unit-tested Python under `tools/`, and has a job that installs nothing run standard-library Python.

Mermaid has no Python parser, and drawing a diagram needs a Chromium. The `mermaid-cli` project publishes a container image that holds the CLI and a Chromium together, so a machine that runs it needs Docker and nothing else. Given a block on stdin, the CLI renders it with no network, and for one that does not render it exits non-zero with the parser's message and writes nothing. Given a markdown file instead, it stops at the first block that fails and writes its output beside the input.

Rendering is not layout review: a diagram can render and still read badly, and GitHub draws with its own Mermaid version.

## Decision

A `check_mermaid` module under `tools/doc_scripts/` and a `mermaid-check` job in `pr-checks.yml`.

- The module finds every fenced `mermaid` block in the repo's tracked markdown, leaving out a fence that sits inside another fence. It renders each block by running the pinned `mermaid-cli` image with the block on stdin, no network and no capabilities. For every block that does not render, not only the first, it reports the file, the line the block starts on and the renderer's first error message.
- The image is pinned by tag in the module. Renovate bumps it from there, and the weekly image tag check reads it from there.
- The job runs on a pull request that changes markdown or the module. It runs on the runner's own `python3` and Docker and checks every block in the repo, so a bump of the image is tried against every existing diagram.
- No pre-commit hook runs it. A person who wants the answer before pushing runs the same module by hand.
- The decisions README's rule about rendering points to the check. Layout stays a manual look.

## Alternatives considered

- **Parse in Node under jsdom, with the outcome decided in Python.** It needs Node and two npm packages in every pre-commit environment. Parsing is also the part of Mermaid that does not draw, so a diagram can parse and still fail to render. A Node-only hook would avoid the Python-to-Node handoff, but its outcome logic would be untested JavaScript, against ADR 0064.
- **A commit-stage pre-commit hook that runs the container.** `pre-commit-checks` runs every hook over every file on every pull request, so each pull request, docs or not, would pull the image and start a browser per diagram, and each commit that touches markdown would wait on Docker. A job scoped to markdown pays only when markdown changes.
- **A push-stage hook beside the job, as `ansible-lint` has.** It would give feedback before the push, at the cost of a second wiring for a check a person can already run by hand.
- **`mmdc` over each markdown file.** It starts one container per file instead of per block, but it stops at the first failing block in a file and writes its output into the directory it reads from.
- **The manual `mmdc` render alone.** It is the rule today. Nothing fails when it is skipped, so a slip merges.
- **GitHub's own rendering.** It shows the error to a reader after the fact and gates nothing.

## Consequences

- A pull request that changes markdown pulls the image and starts a browser per block, so the job takes longer as diagrams are added.
- Running the check by hand needs Docker.
- The image is a third party's, pinned by tag as the repo's other external images are, so a publisher that moves a tag changes what runs. It is given only the text of a block, with no network and no capabilities, and the job holds a read-only token.
- A bump of the image can change what renders, and shows as a failing job on the bump's own pull request.
- A diagram can pass the check and still be hard to read, or fail on GitHub's Mermaid version, so the manual look stays for layout.
- The decisions README's rule about rendering points to the check, which [`doc-checks.md`](../../topics/engineering/ci/doc-checks.md#mermaid-render-check) and [`pipeline.md`](../../topics/engineering/ci/pipeline.md#jobs) describe.

## Invariants

- A Mermaid block that does not render under the pinned image fails the check.
- The check reads markdown and changes nothing, and the container is given nothing but a block's text.

## Non-goals

- Whether a diagram is legible, or whether it matches its Decision.
- Diagram types the pinned renderer does not accept.
- Matching the Mermaid version GitHub draws with.

## Validation

- Unit tests cover finding blocks (a fence inside another fence, tilde and longer fences, an indented fence, an unclosed one), the container command, extracting the renderer's message, and the check's exit status. The container run is replaced by a double bound to the real `subprocess.run` interface ([ADR 0070 (Test doubles binding)](../0070-what-a-unit-tests-doubles-are-bound-to/revision-000.md)).
- The job renders every Mermaid block in the repo on each pull request that changes markdown.

## Reconsideration triggers

- A diagram the pinned image renders that GitHub refuses to draw.
- The image no longer being published, or no longer carrying its browser.
