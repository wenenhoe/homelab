# CD Agent Host: The `cd_agent` Role

`ansible/roles/cd_agent` builds the host side of [ADR 0044 revision 0-c](../../decisions/0044-prod-automation-trigger-and-execution/revision-000-c.md): one sandboxed systemd unit and timer per job, each running as its own unprivileged user, and `sshd` accepting only the operator host. Each unit runs the poll, decide and run step in [`cd-agent-runner.md`](cd-agent-runner.md). The role is the mechanism only. The jobs themselves (names, commands, schedules) are the `cd_agent_jobs` data a caller passes in. No inventory group or playbook applies the role to a host yet; that is the rest of Stage 1 in [`cd-agent.md`](../../projects/cd-agent.md).

## Variables

These four have no default, and the role stops on the first check that finds one missing or malformed:

| Variable | Holds |
| :--- | :--- |
| `cd_agent_runner_source_dir` | The controller's path to `tools/cd_agent/`; the role copies `__init__.py` and `run_job.py` from it. |
| `cd_agent_operator_address` | The one IPv4 address `sshd` accepts. A pattern, CIDR range or out-of-range octet is refused, because the value is written into `sshd`'s configuration. |
| `cd_agent_admin_users` | The only users `sshd` lets in: plain names, none of them a job's user. |
| `cd_agent_jobs` | One entry per job, with unique names. |

A job is `name` (`[a-z][a-z0-9-]{0,22}`), `command` (an argument list), exactly one of `poll_interval` (`5min`: the first run is a minute after boot, then that long after each run ends) and `on_calendar` (a systemd calendar expression), and optionally `cwd`, `on_change` and `timeout` (default `cd_agent_default_timeout`, `1h`). `cwd` and `on_change` are the runner's `--cwd` and `--on-change`.

`cd_agent_repo_url` defaults to this repository's HTTPS URL. The directory variables (`cd_agent_opt_dir`, `cd_agent_etc_dir`, `cd_agent_credentials_root`, `cd_agent_state_root`) default to the paths below.

## What a job gets

For a job named `deploy`:

| Path or name | Holds |
| :--- | :--- |
| `cd-agent-deploy` (user and group) | A system user with `/usr/sbin/nologin` as its shell and its state directory as its home. |
| `/var/lib/cd-agent/deploy` | The runner's state directory ([`cd-agent-runner.md`](cd-agent-runner.md#state-directory)), mode `0700`, owned by the job's user. |
| `/etc/cd-agent/credentials/deploy` | Where the job's credential files go, mode `0700`, owned by the job's user. The directory keeps every other user out whatever a file's own mode. The role creates the directory and no files; delivery is the AppRoles work ([`cd-agent-approles.md`](../../projects/cd-agent-approles.md)). |
| `cd-agent-deploy.service`, `cd-agent-deploy.timer` | The job's units in `/etc/systemd/system`. |

`/etc/cd-agent/credentials` is mode `0711`, so a job's user can reach its own directory but not list the others.

The runner is installed under `/opt/cd-agent/lib/cd_agent/`, owned by root and mode `0644`. It is copied from the controller's checkout when the role runs, not fetched, so the code that decides what runs is never replaced by what it fetches. A change to `tools/cd_agent/` reaches the host the next time the role is applied.

## The unit

Each service is `Type=oneshot` and runs the runner as the job's user, with the job's `command` after `--`. The unit sandboxes the job:

- The filesystem is read-only except the job's own state directory (`ProtectSystem=strict`, `ReadWritePaths=`), with a private `/tmp` and no devices.
- No privilege gain: `NoNewPrivileges`, an empty capability set, `RestrictSUIDSGID`, and a `@system-service` system-call filter.
- Network limited to `AF_UNIX`, `AF_INET` and `AF_INET6`; namespaces, kernel tunables and modules, the clock and other users' processes are out of reach.
- Files the job creates are `0077` by default.

`systemd-analyze security` rates a unit 1.5 (OK). `SuccessExitStatus=75` makes a run that finds the job's lock held a success, not a failure. Command arguments are quoted into `ExecStart`, with `%` and `$` doubled and newlines written as `\n`, so a multi-line `sh -c` script runs as written.

## `sshd`

The role writes `/etc/ssh/sshd_config.d/00-cd-agent.conf`, validated with `sshd -t` before it is installed:

```
AllowUsers <cd_agent_admin_users>
Match Address *,!<cd_agent_operator_address>
    DenyUsers *
```

It sorts first, so it is read before any other drop-in, and `DenyUsers` takes precedence over an `AllowUsers` a later file adds. To check a host, ask `sshd` what applies to a connection from a given address:

```sh
sshd -T -C user=<admin>,addr=<address>,host=probe,laddr=<this host>,lport=22 | grep -E '^(allow|deny)users'
```

The operator host's address prints `allowusers` only; any other address also prints `denyusers *`. This host's other listening ports are not the role's concern: nothing it installs listens. The probe from another host in the VLAN, which [`cd-agent.md`](../../projects/cd-agent.md) requires, is a separate check.

## Also applied

The role installs `git`, `python3`, `openssh-client` and `openssh-server`, and includes [`host_hardening`](../infra/host-hardening.md).

## Not done by the role

- Credential files. Delivery is [`cd-agent-approles.md`](../../projects/cd-agent-approles.md)'s.
- Failure alerts and heartbeats, which depend on [ADR 0072](../../decisions/0072-detecting-scheduled-jobs-that-stop-running/revision-000.md)'s mechanism.
- The jobs' toolchain: an Ansible environment and the pinned collections, which a job's `command` needs to run `ansible-playbook`.
- Removing a job dropped from `cd_agent_jobs`: its user, units and directories stay.

## Testing

The `default` Molecule scenario converges the role on a systemd container, then starts three fixture jobs for real against this repository over HTTPS: a poll job, and two calendar jobs. It asserts what ran and as whom: the commit recorded as deployed matches the one the job ran on, a second start did nothing, a job could not write outside its state directory or read another job's credential and could read its own, and no job's user nor `nobody` could read another job's credential file. It also asserts the directory modes, the timers, the installed runner's contents and ownership, and `sshd`'s effective configuration for the operator address and for others. `invalid_input` runs the role with 14 bad inputs and requires each to be refused by the check that names it. See [`molecule-testing.md`](../engineering/molecule-testing.md).
