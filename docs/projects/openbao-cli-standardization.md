---
id: PROJ-openbao-cli-standardization
title: "OpenBao CLI Access: Native Client, Not docker exec/docker run"
type: project
status: not-started
summary: "Replace the four overlapping bao CLI access patterns (alias, docker exec, docker run, per-host scripts) with a native binary on security and controller, then consolidate the docs describing it."
---

# OpenBao CLI Access: Native Client, Not docker exec/docker run

**Status:** Not started

Builds a native `bao` CLI on `security` and `controller`, replacing
`docker exec`-into-the-live-container and throwaway-`docker run`
patterns everywhere except the one place that structurally can't move
(init/unseal). Design lives in
[`openbao-native-cli-not-docker-based-access.md`](../decisions/drafts/openbao-native-cli-not-docker-based-access.md);
this doc tracks build status only.

## Stages

| # | Stage | Status |
| :-: | :--- | :--- |
| 1 | Spike: version-matched native `bao` on `security`, real TLS, real login/read/write | Not started |
| 2 | Native `bao` on `security` (Ansible-managed) + real TLS, replacing skip-verify/alias | Not started |
| 3 | Init/unseal orchestration: paramiko for the SSH hop, `docker exec` kept for the command | Not started |
| 4 | Native `bao` on `controller` (personal setup) + rewrite the two controller scripts | Not started |
| 5 | Session-scoped token handling everywhere, closing the revoke/unset gaps | Not started |
| 6 | Update every doc's invocation examples to the consolidated model | Not started |
| 7 | Audit all OpenBao-topic docs for consolidation/shortening | Not started |

## Stage detail

### Stage 1 — Spike: version-matched native `bao` on `security`

Time-boxed, throwaway - answers one question: does a downloaded
OpenBao `.deb` matching the Docker image's exact pinned version
install cleanly and produce a CLI that authenticates and reads/writes
against the already-running Docker server over real TLS, pointed at
step-ca's locally-read root cert? Discarded once answered; Stage 2
builds the real Ansible task clean, informed by whatever this finds.

### Stage 3 — Init/unseal orchestration

Only the SSH transport changes (paramiko, not the `ssh` CLI via
`subprocess`) - the remote command stays `docker exec openbao bao
operator init/unseal ...`, kept security-local permanently per the
draft's Decision (the crash-loop-before-cert-issuance constraint).
Needs its own spike first: whether `bao operator unseal`'s per-share
input can go through `paramiko.exec_command()` without a real PTY,
without a share ever touching `ps`/shell history - see the draft's
Assumptions. If that spike says no, this stage's shape changes to
"paramiko for setup only, real interactive `ssh` for the unseal
prompts themselves."

### Stage 7 — Audit for consolidation

Deliberately last: evaluating whether
`openbao.md`/`openbao-auth.md`/`openbao-reinit-runbook.md`/
`openbao-vault-bootstrap.md`/`openbao-backup-restore.md`/
`openbao-r2-read-watcher.md` can merge or shrink only makes sense once
their actual content has settled post-Stage 6 - doing it earlier means
redoing it. Produces a recommendation (which docs merge, which just
shrink because they no longer need to re-explain alias/docker-exec
mechanics inline) and acts on it, not just a report.

## Open items

- Exact wrapper shape for session-scoped token handling (a shell
  function, a `trap`, a small helper script) - not decided; Stage 5
  picks one once Stages 2-4's actual scripts exist to wrap.
- Whether `controller`'s version-pinning needs more than documentation
  (a runtime version check) stays open per the draft's third
  Assumption, revisited only if drift actually causes a problem.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes) - run
before deleting this doc once every stage is Done.

- [ ] Every `Done` stage's rationale exists as a real ADR, or plainly
      didn't need one.
- [ ] Every `Done` stage's current behavior is in a topic doc.
- [ ] Every open item is resolved-and-promoted or moved to where it
      belongs next.
- [ ] Every cross-reference into this doc elsewhere in the repo is
      updated or removed.
