---
id: PROJ-initiative-roadmap
title: "Initiative roadmap"
type: project
status: building
blocked: false
summary: "Add the Roadmap view to the generated project planning (a row per initiative in a kept order, columns for in progress, startable and waiting, projects with no initiative last), the initiative list it reads and the check that keeps the list complete, then accept the decision."
decision: ADR-0082/2
allowed_paths:
  - tools/doc_scripts/generate_doc_indexes.py
  - tools/tests/doc_scripts/test_generate_doc_indexes.py
  - docs/projects/README.md
  - docs/project-planning.md
  - docs/topics/engineering/ci/doc-checks.md
---

# Initiative roadmap

Puts the initiative roadmap into practice as
[ADR 0082 (Choosing the next project)](../decisions/0082-choosing-which-project-to-take-up-next/revision-002.md)
decides. It is one stage: the view, the list it reads and the check on the list change together, or the generator
would fail on a list that does not exist yet.

## Scope

- A numbered initiative list in [`README.md`](README.md), one line per initiative saying what it
  delivers and nothing about its place in the order.
- A `render_roadmap_table` in the generator, and a **Roadmap** section at the top of `project-planning.md` that the
  hook regenerates, with its entry in the document's introduction.
- The check that fails the generator for a `super_project` missing from the list, listed twice or with no project.

Not in scope: assigning an initiative to a project that has none, a field on a project that holds an order, and any date
or mode. Each is its own change.

## Decision

[ADR 0082 (Choosing the next project)](../decisions/0082-choosing-which-project-to-take-up-next/revision-002.md), `approved`.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | The view and its list | In progress | `project-planning.md` has a Roadmap section with one row per initiative in list order, a last row for projects with no initiative, and the columns In progress, Startable and Waiting; the generator fails for each of the three list errors; the unit tests cover the order, the last column and the failures; `doc-checks.md` describes the view. |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] Each Roadmap row lists its projects by dependency depth, then file name, in the column their status and Blocker give, and the rows follow the list's order.
- [ ] A `super_project` value missing from the list, repeated in it or used by no project stops the hook.
- [ ] No frontmatter field of a project holds an order.
- [ ] ADR 0082 revision 2 is `accepted`.

## Agent handoff

Stop conditions are in [`README.md#stop-conditions`](README.md#stop-conditions); they apply without being restated here.

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** any project's frontmatter; any decision revision other than ADR 0082's own.
- **Relevant files and interfaces:** `render_initiatives_table` and `regenerate` in `tools/doc_scripts/generate_doc_indexes.py`.
- **Required checks:** `pre-commit run --all-files`; `uv run pytest` from `tools/`.

## Risks

Could cause rework or delay but blocks nothing now — no live vulnerability, incident, or exposure window
([`docs/README.md#public-repo`](../README.md#public-repo)).

- A long cell, such as an initiative with many startable projects, may need its projects on separate lines.

## Open items

- The one-line goal of each initiative, to be written with the first stage.

The initial order, top first:

1. `pull-based-cd`
2. `tofu-vm-provisioning`
3. `off-site-monitoring`
4. `backup-archive-protection`
5. `controller-separation`
6. `compose-stack-files`
7. `coding-agent-host`

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
