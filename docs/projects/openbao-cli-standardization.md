---
id: PROJ-openbao-cli-standardization
title: "OpenBao CLI Access: Native Client, Not docker exec/docker run"
type: project
status: in-progress
summary: "Replace the four overlapping bao CLI access patterns (alias, docker exec, docker run, per-host scripts) with a native binary on security and controller, then consolidate the docs describing it."
---

# OpenBao CLI Access: Native Client, Not docker exec/docker run

**Status:** In progress

Builds a native `bao` CLI on `security` and `controller`, replacing
`docker exec`-into-the-live-container and throwaway-`docker run`
patterns everywhere except the one place that structurally can't move
(init/unseal). Design lives in
[`openbao-native-cli-not-docker-based-access.md`](../decisions/drafts/openbao-native-cli-not-docker-based-access.md);
this doc tracks build status only.

## Stages

| # | Stage | Status |
| :-: | :--- | :--- |
| 1 | Spike: version-matched native `bao` on `security`, real TLS, real login/read/write | Done |
| 2 | Native `bao` on `security` (Ansible-managed) + real TLS, replacing skip-verify/alias | Not started |
| 3 | Init/unseal orchestration: paramiko for the SSH hop, `docker exec` kept for the command | Not started |
| 4 | Native `bao` on `controller` (personal setup) + rewrite the two controller scripts, with a local version-check against the server | Not started |
| 5 | Session-scoped token handling everywhere, closing the revoke/unset gaps | Not started |
| 6 | Update every doc's invocation examples to the consolidated model | Not started |
| 7 | Audit all OpenBao-topic docs for consolidation/shortening | Not started |

## Stage detail

### Stage 1 — Spike: version-matched native `bao` on `security` (Done)

Time-boxed, throwaway - answered live on `security` with this exact
`2.6.2` pin: the `.deb` installs cleanly, doesn't auto-start anything,
and the native CLI authenticates and reads/writes against the
already-running Docker server over real TLS, using step-ca's
locally-read root cert. Findings (the package's real name, the
shipped-scaffolding cleanup it needs, and the TLS SAN/`-tls-server-name`
mechanics required once `BAO_SKIP_VERIFY` is gone) are folded into the
now-`Decided` draft's Context/Decision - see
[`openbao-native-cli-not-docker-based-access.md`](../decisions/drafts/openbao-native-cli-not-docker-based-access.md).
The spike's own throwaway install on `security` gets torn down before
Stage 2 installs it for real via Ansible.

While in the same de-risking pass, Stage 3's and Stage 4's own open
design questions (below) were resolved too, out of stage order - the
drafts hard gate blocks all of Stage 2 onward equally regardless of
which stage nominally owns a given `Assumptions` entry, so there was
no reason to wait.

### Stage 3 — Init/unseal orchestration

Only the SSH transport changes (paramiko, not the `ssh` CLI via
`subprocess`) - the remote command stays `docker exec openbao bao
operator init/unseal ...`, kept security-local permanently per the
draft's Decision (the crash-loop-before-cert-issuance constraint).
Settled by the Stage 1 de-risking pass: a bare, non-PTY
`paramiko.exec_command()` can't drive `bao operator unseal`'s masked
prompt at all (confirmed live - it hard-fails outright), but a real
PTY allocated on the same channel (`get_pty=True`) can, entirely
programmatically, without a share ever touching argv or `ps` - see the
draft's Context. No fallback to a real interactive `ssh` session is
needed.

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
- Whether `docker/openbao/scripts/`'s shell scripts and
  `openbao_backup/snapshot-push.sh.j2` get rewritten in Python against
  `tools/openbao_utils/` directly, dropping their `python3 -c "from
  ..."` one-liner pattern entirely once a native `bao` binary makes
  the throwaway-container model this project replaces moot anyway -
  moved here from `tools-secrets-package-split.md`'s own open items,
  since it's this project's call (native CLI vs. Python client), not
  that one's.

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
