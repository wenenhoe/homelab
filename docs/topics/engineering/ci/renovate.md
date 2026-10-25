# Renovate

Self-hosted [Renovate](https://docs.renovatebot.com) opens the dependency update pull requests: image tags, GitHub Action pins, Python packages, pre-commit hooks and the pinned release downloads. It runs from [`renovate.yml`](../../../../.github/workflows/renovate.yml) and is configured by [`renovate.json5`](../../../../.github/renovate.json5). The window check that runs after it is in [CI scheduled jobs](scheduled-jobs.md#renovate-schedule-window). How the branches it targets are meant to change is [ADR 0076 (Branch separation)](../../../decisions/0076-keeping-what-production-runs-apart-from-work-in-progress/revision-000.md).

## How it runs

- The workflow runs daily at 17:37 UTC and on `workflow_dispatch`. Running daily rebases open branches and lets vulnerability alerts land the same day.
- `renovate.json5`'s `schedule` separately limits when it may open **new** branches and pull requests: Monday and Thursday, 00:00 to 05:59 `Asia/Singapore`. Branch updates and vulnerability-alert pull requests are not held to it.
- The job's own `GITHUB_TOKEN` is `contents: read`, enough to check the repository out. Renovate authenticates to GitHub as [its own GitHub App](#the-github-app), and the app's installation token is passed as a host rule for `api.github.com` so the custom datasources that read release metadata do not share GitHub's unauthenticated limit.
- Renovate's branches and pull requests are based on `maintenance`, not `main` (`baseBranchPatterns`). `rebaseWhen: behind-base-branch` rebases one only when `maintenance` has moved, which keeps a branch from being rewritten for no reason.
- The first step after checkout merges `main` into `maintenance` ([realignment](#realigning-maintenance)), so the run never starts from a branch that is behind production.
- One run at a time: the `renovate` concurrency group queues a second run behind the first and never cancels it.

## Realigning maintenance

[`ci.branches.realign`](../../../../tools/ci/branches/realign.py) makes `maintenance` contain `main` before Renovate runs, and does only what the two branches need:

| State of the branches | What happens |
| :--- | :--- |
| `maintenance` already contains `main` | Nothing is pushed. |
| `maintenance` is an ancestor of `main` (after a promotion, say) | `maintenance` is fast-forwarded to `main`. |
| They have diverged | `main` is merged into `maintenance` with a merge commit. |
| The merge conflicts | The merge is aborted, `maintenance` is left as it was and the run fails. |

It never rewrites and never forces: every push is a plain push of a commit that has the old tip as an ancestor, so the remote refuses it if `maintenance` moved during the run. History is only added to because Renovate treats a pull request branch as edited when other authors' commits sit under it. `main` is only read.

A failed realignment fails the job before the Renovate step, which has no condition that would let it run anyway. To clear a conflict, merge `main` into `maintenance` locally, resolve it and push that merge; the next run finds the branch current. The push uses the app's token, passed to git as a header for that one command, because the job's own `GITHUB_TOKEN` is refused on `maintenance`. `tools/tests/ci/branches/test_realign.py` runs each case on temporary repositories, and `test_renovate_workflow.py` asserts the step order and that nothing can skip the check.

## Image digests

Every docker image reference is pinned as `name:tag@sha256:digest` ([ADR 0083 (Images a deploy runs)](../../../decisions/0083-making-a-deploy-run-the-images-its-commit-names/revision-000.md)). The `docker:pinDigests` preset adds a digest where one is missing and moves it when a tag is rebuilt or a version changes.

- The docker-compose, dockerfile and ansible managers handle the digest themselves. Each custom regex manager for a docker image needs two things: a `currentDigest` group, `(?:@(?<currentDigest>sha256:[a-f0-9]{64}))?`, and an `autoReplaceStringTemplate` that ends in `{{#if newDigest}}@{{{newDigest}}}{{/if}}`. Without the group Renovate reads no digest; without the template it writes none, or drops the one a bump should keep.
- A manager's tag group must not match `@`: `[^"@]+`, not `[^"]+`, or the tag swallows the digest.
- Renovate compiles patterns with RE2 when it is installed, so a pattern has no lookahead, lookbehind or backreference. Extra named groups are not passed to the template, so it spells out whatever precedes the image (`openbao_image: "`), and a file holding several variables needs one manager per variable.
- Pin and digest-refresh pull requests are two groups, `docker image digest pins` and `docker image digest refreshes (same tag, rebuilt)`. Neither automerges.
- `tools/tests/ci/images/test_remote.py` runs every docker manager over the real tree and fails one that lacks the group or the template, or whose template would change anything but the pin.

## The GitHub App

Renovate authenticates as its own **GitHub App**, installed on this repository alone and used for nothing else ([ADR 0076 (Branch separation)](../../../decisions/0076-keeping-what-production-runs-apart-from-work-in-progress/revision-000.md)). Each run mints an installation token from the app's private key with `actions/create-github-app-token`; the token lasts an hour and is revoked when the job ends. The same token is the platform token, the `api.github.com` host rule and the credential for [realigning `maintenance`](#realigning-maintenance). `renovate.json5`'s `gitAuthor` stays the maintainer's no-reply address: Renovate treats a branch as edited when a commit has another author, so who pushes can change without who authors.

| Setting | Holds |
| :--- | :--- |
| `RENOVATE_APP_CLIENT_ID` (Actions variable) | The app's Client ID, from its settings page. It is not a secret. |
| `RENOVATE_APP_PRIVATE_KEY` (Actions secret) | The whole `.pem` of a private key generated for the app. |

The app's repository permissions, and what each is for. The workflow asks for exactly these, so a token holds nothing the app was not installed with:

| Permission | Access | Used for |
| :--- | :--- | :--- |
| Metadata | Read | Required by every app. |
| Contents | Read and write | Reading the repository and pushing Renovate's branches and the realigned `maintenance`. |
| Pull requests | Read and write | Opening, updating and labelling pull requests. |
| Workflows | Read and write | Updating the pinned action digests in `.github/workflows/`. GitHub refuses a push that changes a workflow file without it. |
| Issues | Read and write | The Dependency Dashboard issue. |
| Commit statuses | Read and write | The `renovate/*` statuses on its branches. |
| Dependabot alerts | Read | `vulnerabilityAlerts` in `renovate.json5`. Not "Dependabot version updates" or "security updates", which would compete with Renovate for the same changes. |

What the app may do on each branch is the rulesets' business, not the token's: it is on the bypass list of the ruleset for `maintenance` and `develop`, so it can push there without a pull request, and on no ruleset for `main`, where it can open a pull request and nothing more. `main`'s ruleset requires a pull request, the checks and an approving review, with no bypass for the app, so the app cannot merge there. Keep the repository setting that lets Actions approve pull requests off.

To rotate the key, generate a second private key in the app's settings, replace the secret, run the workflow once with `workflow_dispatch`, and delete the old key. To change a permission, change it in the app's settings and accept the new permissions on the installation, in the same change as the workflow's `permission-*` inputs and the table above; `tools/tests/ci/branches/test_renovate_workflow.py` fails when the workflow asks for something else.

## Checking a run

- A run that opens nothing on a Monday or Thursday is usually the window check's job to explain; its failure names the time the run started.
- A `403` or `Resource not accessible by integration` in the log names the permission above that the app's token lacks. `Could not create token` or a `401` from the token step means the Client ID or key is wrong, or the app is not installed on this repository.
- The Dependency Dashboard issue lists every update Renovate knows of, including those held back by the schedule or by approval.
- To run it outside the window, dispatch the workflow, then read the log. Pull request creation still waits for the window unless the update is a vulnerability alert.
