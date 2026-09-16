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
| 2 | Native `bao` on `security` (Ansible-managed): install, mask shipped service, real TLS, replacing skip-verify/alias | Not started |
| 3 | Init/unseal orchestration: paramiko for the SSH hop, `docker exec` kept for the command | Not started |
| 4 | Merged `bao_session.py` (`tools/openbao_utils/`, replaces all 3 of `bao-login.sh`/`bao-login-from-controller.sh`/`bao-from-controller.sh`) + native `bao` on `controller` (personal setup) | Not started |
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

### Stage 4 — Merged `bao_session.py` + native `bao` on `controller`

Settled by the same de-risking pass: `docker/openbao/scripts/bao-login.sh`
(previously implied as Stage 2's own territory, being `security`-local)
merges with `bao-login-from-controller.sh`/`bao-from-controller.sh`
into one script, `tools/openbao_utils/bao_session.py`, usable from
either host - no `security`-only script is built separately in
Stage 2. It authenticates via this module's existing `vault_login()`
(`hvac`, `secret_id` read with `getpass` straight into memory, never a
file, never a subprocess argument), then hands off to a real
interactive child shell with `BAO_ADDR`/`BAO_CACERT`/
`BAO_TLS_SERVER_NAME`/`BAO_TOKEN` exported for that child only, so
every native `bao` subcommand keeps working unmodified inside it.
Revokes the token when that child exits, normally or via Ctrl-C - see
the draft's Decision for the confirmed `try/finally`+`KeyboardInterrupt`
mechanics that guarantee this. Auto-detects `security` vs. `controller`
by trying a local `docker exec step-ca ...` first, falling back to the
SSH-fetch-over-`paramiko` path otherwise; `--controller` stays as an
override, not the primary interface. Also carries the local
version-check against the server (see the draft's Decision).

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

- Applying the now-decided session-scoped wrap-and-revoke shape (see
  the draft's Decision - `bao_session.py`'s login-and-forced-cleanup
  pattern) to the other places `BAO_TOKEN` currently gets bare-`export`ed
  with no forced revoke: `openbao-backup-restore.md`'s and
  `openbao-vault-bootstrap.md`'s day-to-day sections. Stage 5's actual
  remaining job - the shape itself isn't in question anymore, only
  where else it needs applying.
- `openbao_backup/snapshot-push.sh.j2` stays a shell script calling the
  native `bao` CLI directly (same Stage 2/3 mechanism as everything
  else), not rewritten in Python/`hvac`: unlike `bao_session.py`, it's
  machine-run and does two fixed operations, but rewriting it against
  `hvac` would mean adopting ADR 0030's programmatic-API-client pattern
  for something that's currently CLI-driven - a bigger, different
  decision (API client vs. CLI) than this project's own scope, and not
  this project's call to make unilaterally.
  [ADR 0031](../decisions/0031-tools-secrets-package-split.md)'s
  original open item conflated this file with `docker/openbao/scripts/`'s
  - they're resolved differently; see the draft's Decision for
  `docker/openbao/scripts/`'s own resolution.

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
