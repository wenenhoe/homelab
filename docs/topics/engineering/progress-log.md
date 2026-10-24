# Progress Log

A weekly and monthly record of what was merged to `main`, written by a scheduled job to the `progress-log` branch. It answers "what did I work on this week, and this month". Why it is a generated branch and not files on `main` is in [ADR 0095 (Progress log)](../../decisions/0095-recording-what-was-worked-on-each-week-and-month/revision-000.md); when the job fires is in [`ci/scheduled-jobs.md`](ci/scheduled-jobs.md#progress-log).

## Reading it

Open the branch's `README.md`. It links the recent weeks and every month.

| File | Holds |
| :--- | :--- |
| `README.md` | The latest weeks side by side, and a link to each month. |
| `weeks/YYYY-Www.md` | One ISO week, Monday to Sunday in Asia/Singapore (UTC+8): a headline count, highlights, the themes the changes fall under, and the changes themselves. |
| `months/YYYY-MM.md` | One month: the same headline and highlights, the themes, and a row per week linking its file. |
| `data/YYYY-Www.json` | The week's changes as the generator read them, which the markdown is rendered from. |
| `state.json` | The last `main` commit read, and the week that was in progress. |

The long parts are collapsed: a week lists its changes under "All N changes" and its project and decision events under a log fold. Counts are merged PRs, or direct commits from before the PR workflow. Dependency updates are counted and not listed.

## What it decides

Everything is by rule from the paths a change touched and its title, with no model and no network call, so the same change always lands in the same place.

- A change is **code** if it touches anything outside `docs/`, **project-doc edits** if it touches only `docs/projects/`, **docs** if it touches other docs and decisions only, and a **dependency update** if it came from Renovate. The generated doc views are ignored when deciding.
- It is listed under a theme: a project (chosen by a state change in the change, then by the project name's words in the title), "Decisions", or the area of the repo most of its code is in.
- Highlights come from the project and decision frontmatter: a project opened, started building or closed, a decision approved or accepted, and an app or role added or removed. A project opened as not-started and deleted within the same span is dropped as scoping churn.

A theme can be named oddly. The fix is a note, not a rule change, unless the same oddity keeps coming back.

## Writing notes

Under the notes marker at the foot of each week file, write whatever the generated text can't say. The generator keeps everything below the marker whenever it rewrites the file, including in a full rebuild. Commit the note to the `progress-log` branch like any other change.

## How a run works

[`progress-log.yml`](../../../.github/workflows/progress-log.yml) checks out `main` in full and the `progress-log` branch beside it, runs [`tools/progress_log`](../../../tools/progress_log/generate.py), and commits and pushes whatever changed. The generator reads only the changes after `state.json`'s commit, so a run costs the same however long the history is. It rewrites only the weeks those changes fall in (and the week that was in progress last time, to drop its marker) and the months they belong to. A week that is over is never rewritten, so its notes are never at risk. A run with nothing new pushes nothing.

The job holds `contents: write`, the only one in the repo's workflows that does, and uses it for one plain push to `progress-log`. It cannot create the branch, delete it, force-push it or touch `main`: the branch's ruleset refuses deletion and force-push, and the push is neither. A rejected push fails the run, and GitHub emails the failure.

## Rebuilding

If `state.json` names a commit that is no longer in `main`'s history, or is missing, the next run rebuilds every week from `main` and keeps the notes. It lands as a normal commit on top of the branch, so nothing is force-pushed and the old versions stay in the branch's history. To force a rebuild after changing the generator's rules, delete `state.json` on the branch and dispatch the workflow.

## Running it by hand

From `tools/`, with the branch checked out in another directory:

```sh
python3 -m progress_log --repo .. --out ../../progress-log-checkout
```

`--full` rebuilds instead of resuming, `--head REV` stops at a commit, and `--repo-url` sets the base for the pull request links. The package imports only the standard library, so it needs nothing installed.

## Limits

- The log reads this repo's public history and nothing else, so it can say what was merged and not how long it took or what was tried first.
- Groupings are heuristics. They are for orienting a reader, not for counting work.
