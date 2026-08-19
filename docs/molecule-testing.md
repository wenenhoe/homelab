# Molecule Testing

Each role is tested in isolation with [Molecule](https://ansible.readthedocs.io/projects/molecule/),
using the co-located convention: a role's scenarios live under
`ansible/roles/<role>/molecule/<scenario>/`. Molecule brings up a real
Docker container per scenario, converges the role into it, verifies the
result, then re-converges to check idempotence — mirroring what
`deploy.yaml` does against real hosts.

## Scenario matrix

| Role | Scenario(s) | What it covers |
| :--- | :--- | :--- |
| `apt` | `default` | Package updates only — no systemd, no privileged mode. |
| `fwupd` | *(none)* | Needs real firmware/LVFS hardware; not containerizable. |
| `docker` | `default` | Installing Docker Engine in a privileged/systemd container. |
| `qemu_guest_agent` | `default` | Package installs; shipped unit still matches the udev-activated shape the role relies on (no `[Install]`/`WantedBy=`). No systemd start/enable path — see [`qemu-guest-agent.md`](qemu-guest-agent.md). |
| `compose` | `default` | Main init/deploy happy path. |
| | `volumes` | Named-volume creation, legacy bind-mount migration, config seeding, teardown. |
| | `scripts` | The two script-deployment paths in `init.yaml` (direct copy vs. volume-seeded). |
| | `build` | The `build: true` branch of `deploy.yaml`. |
| | `cleanup` | `cleanup.yaml` dry-run, keep-content path, and label-fallback teardown. |
| | `reset` | Wiping a volume that mixes seeded config with app-written runtime state restores the config, discards the runtime state; a pure-runtime volume with no seeded content comes back genuinely empty; running without explicit confirmation refuses and leaves everything untouched. |
| `compose_app` | `default` | Batch-driving `compose/` across apps, continuing past a failure. |
| | `strict` | `compose_app_continue_on_error: false`. |
| | `continue_on_error` | One broken app (bad config source) alongside healthy ones: batch reports the failure, healthy apps still deploy, self-managed apps (`bind9`/`caddy`) untouched. |
| `secrets` | `default` | First-run generation + idempotent second run for one `hex`, one `uuid4`, two `manual` (present-empty, present-non-empty) entries; correct length/charset, RFC 4122 v4 shape, `0600` perms. |
| | `manual_missing` | A `manual` entry with no cache file fails the play loudly, naming the secret and pointing at `bootstrap_secrets.py`. |
| `caddy` | `default` | Custom DigitalOcean-DNS Caddy build (xcaddy from source) + deploy. Slowest scenario (Go module compile). |
| | `unregistered` | `caddy_has_compose_app == false` — config renders and image builds, nothing seeded/deployed. |
| `caddy_cert_expiry` | `default` | Stands up a real Caddy target with internal-CA certs (same `caddy_local_certs: true` shape as `caddy`'s own `default` scenario) and runs the check script for real against its live TLS handshake. Caddy's internal issuer defaults leaf certs to a 12h lifetime, so this scenario overrides `caddy_cert_expiry_threshold_days` to `0` to get a genuine live pass at the exact boundary the internal CA can reach — the production `30`-day default (`defaults/main.yaml`) is only exercised structurally, not against a real cert of that age. Also confirms a real `OnFailure=` alert fires for an SNI with no configured site/cert at all. See `telegram_notify` below for why the alert side is only exercised indirectly here. |
| | `no_routed_apps` | The guard clause fires before anything Docker/Caddy-related runs, so this needs no privileged/Docker-in-Docker driver at all (same lightweight shape as `apt`'s own scenario) — a host whose `compose_apps` has no `caddy:` route at all, confirming the role fails loudly naming the missing route rather than proceeding with nothing to check. |
| `telegram_notify` | *(none)* | Library role, no `tasks/main.yaml` and no molecule suite of its own — exercised only indirectly through whatever role includes it (`caddy_cert_expiry` above; `lldap_cert`/`cloud_sync` aren't migrated onto it yet, see `docs/telegram-notifications.md`). |
| `bind9` | `default` | Zone-file aggregation/rendering/reload against a single self-hosting instance. |
| `seaweedfs_bucket` | `default` | Bucket doesn't exist → role creates it against a real throwaway SeaweedFS target, verified by listing the bucket after. |
| | `wrong_credentials` | Mismatched credentials must fail loudly, not get swallowed by `BucketAlreadyExists` tolerance. |
| | `identity_scoping` | Renders the real production `s3-identity.json.j2` (not a synthetic config) against a real SeaweedFS target with two fake backup hosts. Confirms each host's identity can read/write only its own prefix — cross-prefix write and read are both actually denied, not just untested — and that a scoped identity has no Admin-level access (can't remove the bucket). The one scenario that exercises this file at all; every other SeaweedFS-backed scenario uses `molecule_helpers`' own trivial single-identity default instead. |
| `step_ca_client` | `default` | Caches a real, throwaway step-ca's root cert on the host, verified byte-for-byte against the container's actual root. |
| | `not_running` | No running step-ca target at all — the guard at the top of the role fails loudly, before anything else runs. |
| `lldap_cert` | `default` | Deploys the real lldap compose stack on a cold (unseeded) `certs` volume, issues its initial cert against a real step-ca, confirms lldap recovers from the resulting crash loop, and confirms the systemd renewal units are installed correctly — including running the exact `ExecStart`/`ExecStartPost` commands directly and asserting their real side effects (cert serial changes, lldap's start time changing). Doesn't wait on or exercise the timer's own `needs-renewal` gating — see `renewal_timing` below for that. |
| | `renewal_timing` | Issues a real 1-minute-lifetime cert and exercises the installed `cert-renewer@lldap.service` unit's actual `ExecCondition` gating against `step certificate needs-renewal`'s documented 66%-of-lifetime default threshold — confirms a too-early attempt (~10s in) is correctly skipped and a comfortably-due one (~50s in) actually renews. Takes real wall-clock time (~50s), unlike every other scenario in this repo; no `idempotence` step. |
| | `not_running` | No running lldap target at all — the guard at the top of the role fails loudly, before anything step-ca-related runs. |
| `lldap_bootstrap` | `default` | Observer account doesn't exist → role creates it (in `lldap_strict_readonly`) against a real throwaway lldap target, verified by querying its group membership as admin. |
| | `not_running` | No running lldap target at all — the guard at the top of the role fails loudly, naming the missing container, before touching anything. |
| `tinyauth` | `default` | Stands up a throwaway lldap target, runs `lldap_bootstrap` against it for real, then deploys the real tinyauth compose app and waits for it to report healthy — only reachable having already bound to LDAP at boot. Molecule-only; not wired into `deploy.yaml`. |
| `tinyauth_ca_trust` | `default` | Runs `lldap_bootstrap` against a real step-ca-issued lldap target (same dependency chain `tinyauth/default` exercises), then deploys real tinyauth with `tinyauth_ldap_insecure: false` — the scenario that empirically confirmed the SSL_CERT_FILE/Go-cert-pool mechanism `docs/lldap.md` documents, rather than leaving it as an unverified design note. Asserts on `docker logs`-observed process-start count (`>= 2`), not `RestartCount` — that counter turned out to be reset by the scenario's own restart, confirmed live — and `>= 2`, not tinyauth's own `== 0`, since this scenario's whole point is reproducing the cold-start-then-recover race, not avoiding it. |
| | `not_running` | No running tinyauth target at all — the guard at the top of the role fails loudly, before anything CA-bundle-related runs. |
| `backup_agent` | `default` | One schedule per app, always SeaweedFS (no per-target fan-out — that was reverted back to app-host-side simplicity when cloud coverage moved to `cloud_sync`, storage-only). Per-schedule stop-label isolation confirmed behaviorally: happy_app_stop's `StartedAt` changes when its own schedule's real (test-sped-up) cron fires, happy_app_nostop's never does, even though every schedule shares one container. Archives land in the test bucket. Stale-schedule-file removal exercised via a seeded leftover file, guarded so it only runs once (not on the `idempotence` re-run). |
| | `no_stop_apps` | No app on the host opts into `stop_during_backup` — confirms `backup-dockerproxy` (and `DOCKER_HOST`) are entirely absent from the rendered compose.yaml, not just unused. |
| `cloud_sync` | `default` | Real SeaweedFS target standing in for both the source and the R2/B2/OCI destinations (real credentials aren't reachable from CI regardless — see the scenario's own header). Two synthetic backup hosts, one app with no override (must fan out to every default target) and one with `extra_cloud_targets` restricted to a single target (must reach only that one, not the other) — resolved via `hostvars[host].compose_apps`, the same cross-host mechanism the real role uses. `idempotence` covers only the role's own rendering; triggering the real `Type=oneshot` service and asserting the destination buckets' actual contents happens in `verify.yml` instead, deliberately outside the idempotence-checked path — a oneshot job is supposed to report changed every time it fires, which isn't a bug to fix, just not what that check is for. |
| `restore` | `default` | Full restore of a single volume: stop → extract → overwrite → redeploy, with `StartedAt` and content checks. |
| | `multi_volume` | Multiple volumes restored from one archive at different nesting depths, ignoring a decoy and an unrelated app's directory. |
| | `validation_failure` | Missing archive path blocks every destructive step (asserted via unchanged `StartedAt`/content, not just task failure). |
| | `confirmation_declined` | Valid vars/archive but `restore_confirm: false` — same side-effect assertions as `validation_failure`. |

Negative-path scenarios assert on `ansible_failed_task`/`ansible_failed_result`
(task name + a distinctive substring of the failure message) rather than a
bare `rescue:` firing — a bare rescue can't tell the expected failure apart
from an unrelated one (e.g. Docker not ready). See
`ansible/roles/restore/molecule/validation_failure/converge.yml` for the
pattern to copy when adding a new one.

`restore`'s `default`/`multi_volume` skip the `idempotence` step (a
restore is meant to re-execute unconditionally, not converge to a no-op).
`confirmation_declined` skips it because its fixture unconditionally
rebuilds the test archive every run.

`lldap_bootstrap`'s tasks are tagged `molecule-idempotence-notest` (same
mechanism `compose_app` uses): Render/Remove create-then-delete the same
`/tmp` file every run, by design, so its `idempotence` step doesn't
re-exercise the role — only the rest of the scenario (Docker/network
setup, the throwaway lldap target) is checked for a no-op.
`bootstrap.sh`'s own idempotency is a source-level fact, not something
re-checked live.

Run a single scenario:

```sh
cd ansible/roles/apt
molecule test
```

Non-default scenario:

```sh
cd ansible/roles/compose
molecule test -s volumes
```

Every scenario of every role:

```sh
./molecule-test-all.sh          # every role
./molecule-test-all.sh compose  # just one
```

One scenario of one role, without `cd`-ing into it:

```sh
./molecule-test-all.sh compose -s volumes
```

`molecule test --all` doesn't work from `ansible/` directly — Molecule's
scenario glob doesn't recurse into `roles/*/molecule/*/`, and 17 of this
repo's 37 scenarios share the name `default`, which a recursive glob
would reject as a collision. `molecule-test-all.sh` runs `molecule test
--all` once per role directory instead, so each invocation only sees that
role's own unique scenario names.

## `molecule_helpers`

Shared scaffolding for scenarios, not a role under test:

| File | Used for |
| :--- | :--- |
| `playbooks/prepare_dind.yml` | Shared `prepare` playbook (below). |
| `tasks/dind_storage_driver.yaml` | Forces the nested Docker daemon onto `fuse-overlayfs` via `/etc/docker/daemon.json`. |
| `tasks/install_docker_api_requests.yaml` | Installs `python3-requests`, needed by `community.docker` modules that talk to the Docker API directly. |
| `tasks/bootstrap_docker.yaml` | `include_role: docker` for scenarios that assume Docker is already installed, mirroring `deploy.yaml`'s Play 1. |
| `tasks/resolve_compose_apps.yaml` | Resolves a scenario's `compose_apps` against `app_registry`, same merge as `deploy.yaml`. |
| `tasks/start_seaweedfs_test_target.yaml` | Starts a real throwaway SeaweedFS S3 target with a real identity config (single-identity default, or a caller-supplied `molecule_helpers_seaweedfs_identity_json` for scenarios testing scoping across multiple identities — `identity_scoping` and `cloud_sync` both use this); exposes its IP as `molecule_helpers_seaweedfs_ip`. |
| `tasks/start_lldap_test_target.yaml` | Starts a real throwaway lldap target with a self-signed LDAPS cert, reachable under a caller-chosen network alias (needed for TLS hostname verification); exposes its IP as `molecule_helpers_lldap_ip`. |
| `tasks/reset_coverage_data.yaml` | Clears a scenario's `molecule-coverage` JSONL at `prepare` time (the callback appends, doesn't truncate). No-op if `MOLECULE_COVERAGE_DIR` isn't set. |
| `requirements.yml` / `role-requirements.yml` | Shared Galaxy collection/role deps (`community.docker`, `ansible.posix`). |

### Why `fuse-overlayfs`

The test container's own root filesystem is already overlay-mounted by
the host's Docker, and `overlay2` can't stack a second overlay on top of
that (`failed to mount ... fstype: overlay`). `fuse-overlayfs` is a
userspace overlay implementation that avoids that kernel-level stacking
restriction while still getting real copy-on-write, unlike `vfs`'s
full-copy-per-layer behavior — meaningfully faster for image pulls/builds
in the nested daemon. Test scaffolding only — real hosts keep using
`overlay2`.

### Shared `prepare`

Every Docker-in-Docker scenario except `bind9` needs the `fuse-overlayfs`
override and `python3-requests`, so they all point at one playbook
instead of each keeping its own:

```yaml
# molecule.yml
provisioner:
  name: ansible
  playbooks:
    prepare: ${MOLECULE_PROJECT_DIRECTORY}/../molecule_helpers/playbooks/prepare_dind.yml
    converge: converge.yml
    verify: verify.yml
```

`bind9` keeps its own `prepare.yml` (it manages its own `daemon.json` and
would fight over the same file, so it forces `fuse-overlayfs` via a
systemd drop-in instead). `apt` keeps a minimal `prepare.yml` whose only
job is calling `reset_coverage_data.yaml`.

### Base config

`.config/molecule/config.yml` at the repo root is Molecule's auto-discovered
base config, deep-merged into every scenario before that scenario's own
`molecule.yml` applies. It supplies the shared `dependency` collections
and `provisioner.env` to every scenario — nothing to add for a new one
beyond its own `molecule.yml`.

## Adding a new scenario

1. Copy an existing scenario directory (e.g. `compose/molecule/default`
   for anything deployed via Compose).
2. If the role assumes Docker is running, point `converge.yml` at
   `molecule_helpers`'s `bootstrap_docker.yaml` (and
   `resolve_compose_apps.yaml` if it uses `app_registry`/`compose_apps`).
3. If it needs Docker-in-Docker, point `prepare` at
   `molecule_helpers/playbooks/prepare_dind.yml` unless, like `bind9`,
   the role's own tasks conflict with its `daemon.json` write.
4. Don't add `dependency.options` or a `provisioner.env` block — the base
   config already supplies both to every scenario.
5. Run `molecule test` locally before opening a PR — there's no CI for
   this yet.

## Coverage

See [`molecule-coverage/README.md`](../ansible/molecule-coverage/README.md)
for the task/loop/branch coverage tool that runs on top of these
scenarios and gates CI (see [`ci.md`](ci.md#molecule-coverage-gate)).

## What molecule scenarios can't catch: tag wiring

Every `converge.yml` calls its role directly (`include_role: name:
bind9`), never through `deploy.yaml`, so the `images`/`infra` tag scheme
(see [`deployment-flow.md`](deployment-flow.md#tags)) is invisible to
these scenarios — nothing here exercises `deploy.yaml`'s own `Include
<role>` wrapper tasks that `--tags images` actually depends on. A
refactor that renames a task or swaps `include_role` for `import_role` in
that chain could break `--tags images`/`--tags infra` silently. Verify
manually before trusting a change to it:

```sh
ansible-playbook deploy.yaml --tags images --limit <host> -vvv | grep "TASK \["
```

and confirm only the expected tasks show up.
