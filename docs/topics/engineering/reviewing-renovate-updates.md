# Reviewing and Merging Renovate's Updates

How the open Renovate pull requests into `maintenance` ([`branching.md`](branching.md#dependency-updates)) are read for breaking changes and merged, and how the batch is then put up for promotion, with [`tools/renovate_merge`](../../../tools/renovate_merge). It is run by the maintainer, or by a session the maintainer starts that is shown its summary; it merges under the maintainer's own `gh` login, and a session never holds one.

Run it from `tools/` in a clone of the repository:

```bash
cd tools
uv run python -m renovate_merge summary --repo ..                   # read the pull requests, write the summary
uv run python -m renovate_merge merge ../.git/renovate-merge/summary.json --repo ..          # merge those at level none
uv run python -m renovate_merge merge ../.git/renovate-merge/summary.json 123 125 --repo ..  # merge these, whatever their level
uv run python -m renovate_merge promote --repo ..                    # open the pull request into main, and stop
```

## The summary

`summary` lists the open pull requests into `maintenance` (`--base` names another branch; `main` is refused unless [`--allow-main`](#a-repository-whose-main-deploys-nothing) is given) whose head branch starts with `renovate/`, is in this repository, and whose author's login names Renovate. For each it reads the description Renovate wrote:

- The **table of updates**: each package with the version it moves from and to. A digest, even one that starts with a digit, is not a version, and a pin or lockfile row with no old version is not listed. A version after a range operator (`==6.0.3`, `^1.2.3`) is read as that version. A change of the first number is `major`; a change of the second number of a `0.x` version is `pre-1.0 minor`, since semver lets that break.
- The **release notes** section, with Renovate's HTML wrapping removed. A pin, a digest refresh or a lockfile update has none.
- The **lines that look like a breaking change**, found by a word search over the release notes:

| Category | Matches | Strength |
| :--- | :--- | :--- |
| breaking | `BREAKING`, an incompatibility, a `feat!:` commit | stronger |
| warning | a `⚠` anywhere in the description (Renovate's own marker), a GitHub `[!WARNING]` or `[!CAUTION]` alert in the notes | stronger |
| security | a CVE or advisory identifier | stronger |
| removal, deprecation, migration or rename, changed default | the words for each | weaker |

The weaker words are not matched in an entry that opens like routine commit work (`fix:`, `refactor:`, `chore:`) or under a heading of fixes, since those describe the project's own tidying. A `Removed` or `Deprecated` heading counts only when something other than `Nothing` or `None` is listed under it.

Each pull request gets a level:

| Level | When |
| :--- | :--- |
| `breaking` | A major version, a stated breaking change or a warning. |
| `notable` | Any weaker match, or a `0.x` minor bump. |
| `none` | Nothing matched. This is the absence of a match, not evidence that nothing changes. |

The summary prints to stdout as Markdown, most severe first, and is written with a JSON copy to `summary.md` and `summary.json` in `renovate-merge/` inside the git directory (`--out` changes it), so neither shows up as an untracked file. The release notes are upstream text that anyone who publishes a release can write. The Markdown says so at the top and quotes every note and every matched line in a code fence longer than any run of backticks inside it, so what is quoted cannot end the quote. A reader, a person or a session, takes it as data. `--notes-characters` limits how much of each package's notes is printed, so that a long first package of a grouped pull request does not hide the others; the level is worked out from all of the notes. The notes are only what Renovate copied into the description, which for a project that tags several releases between two versions can be one release's entry and not all of them: for a `0.x` bump, read the project's own changelog.

## The merge

`merge` reads a `summary.json` and merges the pull requests named after it, in number order, or with none named every one at level `none`. A pull request at any other level is merged only when its number is given: naming it is the statement that its notes were read.

It first checks that `gh` is logged in and reads, once, the checks the rulesets require on the branch, and asks once for the whole list (`--yes` skips the question; with no terminal and no `--yes` it merges nothing). Then for each pull request it:

1. Reads its state from GitHub and leaves it alone unless it is still open on the summary's branch and its **head is the commit the summary read**. Renovate force-pushes a branch when it updates it, so a head that has moved carries notes nobody read; run `summary` again.
2. Waits until every required check has passed, polling every 20 seconds for up to about 90 minutes. A required check not reported yet is waited for, a skipped one counts as passed, and one that failed or was cancelled leaves the pull request open.
3. Runs `gh pr merge --merge --delete-branch --match-head-commit <that commit>`. GitHub refuses a merge whose head is not the commit named, so a push between the last read and the merge cannot slip in.

A pull request that is left, for any reason, is reported with the reason and the run goes on to the next; the run exits non-zero when any was left. It never passes `--admin`: `maintenance` requires a pull request and the checks and no review, so a pull request whose checks passed merges without the bypass, and one GitHub refuses stays open with GitHub's own reason. It does not merge into `main`, whatever the summary says, unless `--allow-main` is given to `merge` as well: a merge there can be a deploy.

`--dry-run` reads each pull request as it stands, prints whether it would merge, still has checks to pass or failed, and merges and asks nothing.

## A repository whose `main` deploys nothing

In this repository a merge to `main` is a deploy, which is why `main` is refused as a base. The tool also serves a repository where Renovate's pull requests target `main` and nothing deploys from it. There `--allow-main` is given to both commands:

```bash
repo=..                  # the checkout
summary="$repo/.git/renovate-merge/summary.json"   # the file `summary` writes
uv run python -m renovate_merge summary --repo "$repo" --base main --allow-main
uv run python -m renovate_merge merge "$summary" --repo "$repo" --allow-main
```

The flag is not read from `summary.json`: a summary that names `main` is refused by `merge` without it, so a file cannot grant it to itself. With the flag `merge` asks for the branch name to be typed (`Type 'main' to merge them:`, not `yes`), and `--yes` is refused with it, so a merge into `main` is never unattended. Everything else is as above, including the wait for the required checks and the absence of `--admin`. `promote` only knows `maintenance` and `main` and is not used there.

### Checks the rulesets do not serve

`merge` reads the required checks from the branch rulesets. GitHub does not serve them for a private repository on a free plan (the call fails with HTTP 403), and classic branch protection is limited the same way, so there is nothing to read and GitHub requires nothing. `--require-check NAME`, repeated for each check, names the ones to wait for instead and skips the read:

```bash
# paste alone; it waits for the summary file, the checkout and two check names (workflow/job)
read -r -p 'summary file: ' summary; read -r -p 'checkout: ' repo; read -r -p 'first check: ' check_one; read -r -p 'second check: ' check_two
```

```bash
uv run python -m renovate_merge merge "$summary" --repo "$repo" --allow-main --dry-run --require-check "$check_one" --require-check "$check_two"
```

The names are the ones `gh pr checks <number>` prints. The wait is the same: a named check not reported yet is waited for, a skipped one counts as passed, and one that failed or was cancelled leaves the pull request open. A name no check ever reports is waited for until the time limit, so run `--dry-run` first: it says `checks still to pass` for a name that does not match. GitHub enforces nothing in such a repository, so the named checks are the only gate besides the head commit the summary read.

## Promoting

`promote` opens the pull request that promotes `maintenance` into `main` ([`branching.md`](branching.md#promoting)) and stops. It never merges it: a merge to `main` is a deploy, so that stays the maintainer's, made by hand with a merge commit and the bypass.

It fetches `main` and `maintenance` and takes the batch from git: the pull requests merged into `maintenance` along its own line since `main` last held it, which leaves out a merge of `main` into `maintenance` and anything `main` already has. Commits made straight on `maintenance` are listed apart. It reads those pull requests from GitHub and gives each Renovate one the same level `summary` gives, so the description is a table of number, title, level and the categories matched. It carries no release-note text, and each title is an inline code span so a package name such as `@types/node` notifies nobody. A pull request GitHub no longer lists is shown by its branch name with no level.

The description has no [promotion checklist](ci/pipeline.md#promotion-checklist) markers, so the workflow that writes that block appends it. When a pull request from `maintenance` into `main` is already open it is reported and left as it is, since the workflow keeps its block in the description. It asks once before opening (`--yes` skips the question; with no terminal and no `--yes` it opens nothing), `--dry-run` prints the title and description and opens nothing, and it stops when `maintenance` holds nothing `main` lacks.

## After a merge

Renovate rebases its other open branches onto `maintenance` at its next run (`rebaseWhen: behind-base-branch`, [`renovate.md`](ci/renovate.md#how-it-runs)); the tool does not update a branch itself, because a commit by anyone but the bot makes Renovate treat the branch as edited. Merging several pull requests in one run therefore merges each at the checks it already had. The checks run again on the pull request that promotes `maintenance` to `main` ([`branching.md`](branching.md#promoting)), over all of them together.

The tool starts `gh` and `git` through `land_series.run`, and reads the required checks with `land_series.land.required_checks`, so a missing program, a hung one and a failed one are told apart as they are in [`landing-a-series.md`](landing-a-series.md#failures-and-the-network). Reads are tried up to three times when the failure looks like a dropped connection; a merge is never repeated.
