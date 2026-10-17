# Renovate

Self-hosted [Renovate](https://docs.renovatebot.com) opens the dependency update pull requests: image tags, GitHub Action pins, Python packages, pre-commit hooks and the pinned release downloads. It runs from [`renovate.yml`](../../../../.github/workflows/renovate.yml) and is configured by [`renovate.json5`](../../../../.github/renovate.json5). The window check that runs after it is in [CI scheduled jobs](scheduled-jobs.md#renovate-schedule-window). How the branches it targets are meant to change is [ADR 0076 (Branch separation)](../../../decisions/0076-keeping-what-production-runs-apart-from-work-in-progress/revision-000.md).

## How it runs

- The workflow runs daily at 17:37 UTC and on `workflow_dispatch`. Running daily rebases open branches and lets vulnerability alerts land the same day.
- `renovate.json5`'s `schedule` separately limits when it may open **new** branches and pull requests: Monday and Thursday, 00:00 to 05:59 `Asia/Singapore`. Branch updates and vulnerability-alert pull requests are not held to it.
- The job's own `GITHUB_TOKEN` is `contents: read`, enough to check the repository out. Renovate authenticates to GitHub with a separate token, the `RENOVATE_TOKEN` Actions secret, and the same token is passed as a host rule for `api.github.com` so the custom datasources that read release metadata do not share GitHub's unauthenticated limit.
- One run at a time: the `renovate` concurrency group queues a second run behind the first and never cancels it.

## Image digests

Every docker image reference is pinned as `name:tag@sha256:digest` ([ADR 0083 (Images a deploy runs)](../../../decisions/0083-making-a-deploy-run-the-images-its-commit-names/revision-000.md)). The `docker:pinDigests` preset adds a digest where one is missing and moves it when a tag is rebuilt or a version changes.

- The docker-compose, dockerfile and ansible managers handle the digest themselves. Each custom regex manager for a docker image needs two things: a `currentDigest` group, `(?:@(?<currentDigest>sha256:[a-f0-9]{64}))?`, and an `autoReplaceStringTemplate` that ends in `{{#if newDigest}}@{{{newDigest}}}{{/if}}`. Without the group Renovate reads no digest; without the template it writes none, or drops the one a bump should keep.
- A manager's tag group must not match `@`: `[^"@]+`, not `[^"]+`, or the tag swallows the digest.
- Renovate compiles patterns with RE2 when it is installed, so a pattern has no lookahead, lookbehind or backreference. Extra named groups are not passed to the template, so it spells out whatever precedes the image (`openbao_image: "`), and a file holding several variables needs one manager per variable.
- Pin and digest-refresh pull requests are two groups, `docker image digest pins` and `docker image digest refreshes (same tag, rebuilt)`. Neither automerges.
- `tools/tests/ci/images/test_remote.py` runs every docker manager over the real tree and fails one that lacks the group or the template, or whose template would change anything but the pin.

## The token

`RENOVATE_TOKEN` is a **fine-grained personal access token**, limited to this repository. Its repository permissions, and what each is for:

| Permission | Access | Used for |
| :--- | :--- | :--- |
| Metadata | Read | Required by every fine-grained token. |
| Contents | Read and write | Reading the repository and pushing Renovate's branches. |
| Pull requests | Read and write | Opening, updating and labelling pull requests. |
| Workflows | Read and write | Updating the pinned action digests in `.github/workflows/`. GitHub refuses a push that changes a workflow file without it. |
| Issues | Read and write | The Dependency Dashboard issue. |
| Commit statuses | Read and write | The `renovate/*` statuses on its branches. |
| Dependabot alerts | Read | `vulnerabilityAlerts` in `renovate.json5`. Not "Dependabot version updates" or "security updates", which would compete with Renovate for the same changes. |

Create it under the account that owns the repository, with the repository as its only resource and an expiry. To rotate it, create a new token with the same permissions, replace the secret, run the workflow once with `workflow_dispatch`, and delete the old token.

## Checking a run

- A run that opens nothing on a Monday or Thursday is usually the window check's job to explain; its failure names the time the run started.
- A `403` or `Resource not accessible by personal access token` in the log names the permission above that the token lacks.
- The Dependency Dashboard issue lists every update Renovate knows of, including those held back by the schedule or by approval.
- To run it outside the window, dispatch the workflow, then read the log. Pull request creation still waits for the window unless the update is a vulnerability alert.
