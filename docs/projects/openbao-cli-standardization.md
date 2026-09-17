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
| 2 | Native `bao` on `security` (Ansible-managed): install, mask shipped service, real TLS, replacing skip-verify/alias | Done |
| 3 | Init/unseal orchestration: paramiko for the SSH hop, `docker exec` kept for the command | Done |
| 4 | Merged `bao_session.py` (`tools/openbao_utils/`, replaces all 3 of `bao-login.sh`/`bao-login-from-controller.sh`/`bao-from-controller.sh`) + native `bao` on `controller` (personal setup) | Done |
| 5 | Session-scoped token handling everywhere, closing the revoke/unset gaps | Not started |
| 6 | Delete the two now-unused artifacts: `ansible/roles/openbao_backup/` and `docker/openbao/scripts/` | Not started |
| 7 | Update every doc's invocation examples to the consolidated model | Not started |
| 8 | Audit all OpenBao-topic docs for consolidation/shortening | Not started |

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

### Stage 2 — Native `bao` on `security` (Done)

New role, `ansible/roles/openbao_cli/`, run last in `deploy.yaml`'s
Play 6 (after openbao's own `step_ca_cert` instance issues its leaf
cert — the TLS check below needs it live). No new open questions: every
mechanic here was already confirmed live by Stage 1's spike, so this
stage is a mechanical translation of that spike into an idempotent
Ansible role, not new de-risking.

Version match is checked against the *running server*, not a hardcoded
commit string: the role reads both `bao version` (native) and `docker
exec openbao bao version` (server) and fails loudly on any mismatch,
before and after installing — so a future bump to
`ansible/roles/openbao`'s own `openbao_image` tag can't silently drift
out of sync with this role's `openbao_cli_version` default. The `.deb`
download is checksummed (`sha256`, from that release's own
`checksums.txt`) rather than trusted on name/size alone.

Masking the shipped `openbao.service` unit and deleting
`/opt/openbao`/`/etc/openbao` both happen unconditionally on every run,
not only right after a fresh install — confirmed directly against the
package's own `postinst`/`preinst` that a stray reinstall regenerates
that scaffolding, so removal has to be idempotent-safe to rerun, not a
one-time cleanup step.

Closing task doubles as this stage's own acceptance check: a real
`bao status` call over real TLS (`-tls-server-name`, step-ca's cached
root cert, no `BAO_SKIP_VERIFY`) against the already-running server.

### Stage 3 — Init/unseal orchestration (Done)

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

Built as `tools/openbao_utils/init_unseal.py` (`init`/`unseal`
subcommands, plain `sys.argv` dispatch matching this package's other
scripts - see the module's own docstring for the full split between
the two). `init`'s own command needs no PTY at all - confirmed against
the real CLI's usage text that it takes no interactive input - so it
reuses `client.exec_command()`'s existing non-PTY shape from
`utils.repo.fetch_root_cert()` rather than a new pattern. Neither
subcommand's output is captured, logged, or written anywhere by this
script; both print directly to the operator's own terminal, for the
same reason this has never been an Ansible task (`openbao.md`'s Init
and unseal section).

Confirmed live (a real 3-share/2-threshold instance) rather than left
as an open question: submitting one share of two - still sealed
afterward, `Unseal Progress 1/2` - exits 0, same as a share that
completes the unseal. `bao operator unseal` evidently doesn't follow
`bao status`'s own sealed=2 exit-code convention at all; its exit code
tracks whether the command itself ran, not the resulting seal state.
`init_unseal.py`'s `unseal` subcommand fails loudly on a nonzero exit
accordingly - a real failure, not partial progress.

### Stage 4 — Merged `bao_session.py` + native `bao` on `controller` (Done)

`docker/openbao/scripts/bao-login.sh`/`bao-login-from-controller.sh`/
`bao-from-controller.sh` all retired at once, replaced by one script,
`tools/openbao_utils/bao_session.py`, usable from either host. It
authenticates via the existing `openbao_utils.client.vault_login()`
(`hvac`, `secret_id` read with `getpass` straight into memory, never a
file, never a subprocess argument), then hands off to a real
interactive child shell with `BAO_ADDR`/`BAO_CACERT`/
`BAO_TLS_SERVER_NAME`/`BAO_TOKEN` exported for that child only, so
every native `bao` subcommand keeps working unmodified inside it, and
revokes the token when that child exits - normally or via Ctrl-C, per
the draft's already-confirmed `try/finally`+`KeyboardInterrupt`
mechanics. Auto-detects `security` vs. `controller` by trying a local
`docker exec step-ca ...` first, falling back to the
SSH-fetch-over-`paramiko` path (`utils.repo.fetch_root_cert`)
otherwise; `--controller` stays as an override, not the primary
interface.

The version check compares local `bao version` against the server's
own reported version, but not via `docker exec` the way
`ansible/roles/openbao_cli` checks it: `bao_session.py` reads it from
the already-authenticated `hvac.Client`'s `sys.read_health_status()`
call instead (openbao.org's own `/sys/health` docs confirm a plain
`"version"` field on a 200 response, e.g. `"2.6.2"` - no `v` prefix,
no build hash), advisory-only, warning rather than failing on a
mismatch since a successful login has already proven the server
reachable.

`controller`'s own native `bao` is a personal, non-Ansible-managed
install step, added to `README.md`'s Setup section rather than a new
topic doc (Stage 8 is where OpenBao's docs get consolidated) - same
version-pinned `.deb` and checksum `ansible/roles/openbao_cli` already
uses for `security`, since this controller also runs Ubuntu, followed
by the same mask-and-scaffolding-removal steps that role performs, run
by hand instead of by Ansible.

### Stage 5 — Session-scoped token handling everywhere

Two wrapper shapes now cover the two needs found while resolving the
open items below - `bao_session.py` (Stage 4) for interactive,
multi-command, single-host access, and a plain shell login-run-revoke
`trap` for fixed, unattended one-shot scripts.
`openbao-vault-bootstrap.md`'s day-to-day flow needed no new decision:
it already fits `bao_session.py`'s shape as-is (single host, several ad
hoc commands) - just needs its example swapped over (Stage 7), and the
forced revoke comes along for free.

`openbao-backup-restore.md`'s flow needed a real decision, not just a
wrapper choice: `snapshot-push.sh.j2` moves off `docker exec`/`docker
cp` and off `security` entirely, since `bao operator raft snapshot
save` was confirmed live as a client-side download (see the draft's
Context) - nothing about it ever actually needed `security`-local
execution, that was only ever a `docker exec` side effect. The
rewritten script runs as one process on `controller`, rehoused at
`tools/openbao_utils/scripts/snapshot-push.sh` (see the draft's
Decision for why that subdirectory, not loose in `openbao_utils`'s own
root), using its own shell-based login+revoke `trap`, replacing the
current mint-on-`controller`/paste-on-`security` manual handoff
entirely. `rclone.conf` is built as a temp file at run time from four
values read directly out of Vault via `bao kv get` (`controller`'s
existing policy already grants this - no new grant needed), and the
GPG public key needs no new mechanism at all: it's a plain repo file
`controller` already has checked out. This is also what empties out
`ansible/roles/openbao_backup/` - see Stage 6.

### Stage 6 — Delete the two now-unused artifacts

Two directories end up with nothing left in them, for two different
reasons, and both get removed here rather than left as dead weight:
`ansible/roles/openbao_backup/` (tasks, templates, its Molecule
scenario) once Stage 5's rewrite moves its script, config, and working
directory to `controller` entirely - `ansible.md`'s role table and
`deployment-flow.md`'s Play 10 get updated in the same pass, not left
pointing at a role that no longer exists. `docker/openbao/scripts/`
separately empties out once Stage 4 merges its three occupants into
`bao_session.py` - `snapshot-push.sh.j2` never lived there, so this
is unrelated to Stage 5's own cleanup, just discovered alongside it.
Depends on Stages 4 and 5 both being Done.

### Stage 8 — Audit for consolidation

Deliberately last: evaluating whether
`openbao.md`/`openbao-auth.md`/`openbao-reinit-runbook.md`/
`openbao-vault-bootstrap.md`/`openbao-backup-restore.md`/
`openbao-r2-read-watcher.md` can merge or shrink only makes sense once
their actual content has settled post-Stage 7 - doing it earlier means
redoing it. Produces a recommendation (which docs merge, which just
shrink because they no longer need to re-explain alias/docker-exec
mechanics inline) and acts on it, not just a report.

## Open items

None currently — the exit-code question Stage 3 carried forward has
been confirmed live (see that stage's own detail above) and resolved
into `init_unseal.py` itself.

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
