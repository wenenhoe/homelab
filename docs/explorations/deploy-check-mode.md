---
id: EXP-deploy-check-mode
title: "Can `deploy.yaml` run in check mode and report what a deploy would change?"
type: exploration
status: open
summary: "What stops `deploy.yaml --check` from finishing today, why a check that finishes can still report a change that is not there, and how far to take check mode on a deploy."
topic: deployment-platform
---

# Can `deploy.yaml` run in check mode and report what a deploy would change?

The gateway's play is checked with `--check`, and the docker role already marks
two of its read-only tasks `check_mode: false` so a check run has a file to read.
`deploy.yaml` as a whole has not been run that way. A check that finished would
say what a deploy changes before it applies, and could report drift on a
schedule. The question is what it takes for the result to be right, not only for
the run to finish.

## What bears on it

- **Where it stops.** A trial of `deploy.yaml --check` limited to `services` and
  `localhost` stopped at the first task that reads from a skipped task's result,
  three times in a row, each time one step further on:

  | Where | Task | Why it fails |
  | :--- | :--- | :--- |
  | `secrets/vault_login.yaml` | The read of the step-ca root certificate, the temp file for it and the copy into it | `docker_container_exec` declares no check-mode support and is skipped, so its result has no `stdout`; the temp file and the copy depend on it |
  | `docker/main.yaml` | The read of the Debian architecture and of the Compose version | `command` is skipped under `--check`, so its output is empty |
  | `secrets/ensure_secret.yaml` | The read of the manual secrets, and `ensure_vault_secret` for the generated ones | Neither runs under `--check`, so `secrets_generated` lacks every key that comes from the store; the repo's own module sets `supports_check_mode=False`, and it creates a secret that does not exist |

  With `check_mode: false` on the read-only tasks of the first two rows the run
  passed the secrets play and the docker role. The third row was not tried.
- **A check can pass and be wrong.** With the architecture read skipped, the
  docker role's apt repository task rendered an empty architecture and reported
  `changed` on a host that matched. It was not drift. Making the read run turned
  it into `ok`. A skipped read does not always stop the run; it can render from
  an empty value and report a change that is not there, or hide one that is.
- **How many tasks.** A scan of the roles and playbooks found 46 `command`,
  `shell` or `docker_container_exec` tasks with a registered result, of which 39
  set no `check_mode`. Most are in Molecule helpers and bootstrap playbooks
  outside the deploy path. Five are in the two roles the trial reached.
- **`ensure_vault_secret` is a write.** It reads a secret and creates it first
  when nothing is stored. A check mode for it must read, return the stored value,
  and report that it would create when nothing is there, without writing.
- **Not examined.** The plays after the secrets read: Caddy and DNS, the compose
  role, the image builds and the handlers; and what each module they use does
  under `--check`. Only the `services` host was tried.

## Options

- **Make each registered read check-safe.** `check_mode: false` on read-only
  tasks, and a read-only check path for `ensure_vault_secret` with its tests. It
  keeps one play and gives a real preview. It costs a change to a module and an
  audit of every task the deploy reaches, and it leaves the first row's pattern
  to be kept by hand.
- **Add a check that forbids the pattern.** A test, like the one that checks
  `no_log` on the secrets tasks, that fails a registered `command`, `shell` or
  exec task with no `check_mode` set. It makes the pattern a rule, not a habit,
  and it can be added with or without the option above.
- **Run check mode on a subset.** Skip the secrets play under `--check` by
  supplying `secrets_generated` another way, or limit the check to tags. It
  avoids the module change. It reports less than a deploy does, and a second path
  into the secrets role is a way to be wrong.
- **Do not support it.** Preview a change by rehearsing it on a clone, as
  [`production-rebuild-rehearsal.md`](production-rebuild-rehearsal.md) weighs for
  the gateway. It needs no changes to the roles. It costs a clone and does not
  report drift on the live host.

## Leaning

Make each registered read check-safe, and add the check that forbids the
pattern, so the false positive cannot return. The module's read-only path is the
part to design first. What would change it: an audit of the later plays that
finds a module with no usable check mode and no read-only substitute, which
would favour the clone.
