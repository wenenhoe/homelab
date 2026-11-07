# Explorations

An exploration holds a question that has no chosen solution yet: the facts
that bear on it, the options, and what each would cost. It is where thinking
happens before a decision exists, so a [decision record](../decisions/README.md)
is only written once a choice is made. It is not a plan, a record of what was
decided, or a description of current behavior; those are
[`projects/`](../projects/README.md), [`decisions/`](../decisions/README.md) and
[`topics/`](../topics/README.md).

Open one when a question is worth writing down before it can be answered: two
or more real options, a fact that has to be found first, or a
reconsideration trigger of an accepted decision that has fired. Skip it for a
question one person can answer in a sentence.

## Shape

One file per question, `<slug>.md`, with no number. Use
[`TEMPLATE.md`](TEMPLATE.md). The frontmatter carries `id` (`EXP-` and the
slug), `type: exploration`, `title` (the question, without naming a solution),
`summary`, `topic` (the decision topics), `status: open` and optionally
`related` (decision lineages it bears on). The body holds the question, the
facts that matter, the options with what each would cost, and optionally a
leaning.

## How one ends

The pull request that ends an exploration deletes it. There is no archive and
no `closed` state: git holds the history, and the options that lost move into
the new record's Alternatives. It ends in one of three ways:

- **A decision is written.** A full or light record, `working` or
  `approved` according to whether assumptions remain. Its Alternatives carry the
  options the exploration weighed.
- **A project is opened** for work that needs no decision.
- **The question is dropped.** The pull request says why in its description.

When a reconsideration trigger of an `accepted` revision fires, open an
exploration; it ends in a new revision of that lineage or is dropped.

## Rules

- **Nothing durable points at an exploration.** It is deleted when it ends, so
  a link from a decision, topic doc, project or comment would dangle.
  `check_doc_drift.py` fails any file outside this directory that names one,
  apart from the generated [planning view](../project-planning.md#open-explorations),
  which lists the open ones. An exploration may link to anything.
- **It stays small.** A question that grows a design is a decision that has
  not been written yet.
- **It does not go stale.** The planning view shows when each last changed (a
  change not yet committed counts as today, since the commit being made is
  its newest), and the generator warns about one untouched for longer than the limit in
  [`doc_explorations.py`](../../tools/doc_scripts/doc_explorations.py).
- **No incident detail.** The rule in
  [`docs/README.md#public-repo`](../README.md#public-repo) applies.
