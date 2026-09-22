---
id: PROJ-ansible-collections-audit
title: 'Ansible Roles: Native Collection Module Audit'
type: project
status: building
blocked: false
summary: Replace hand-rolled command/shell/uri tasks in ansible/roles/* with maintained collection modules where one fits.
---

# Ansible Roles: Native Collection Module Audit

Sweeps `ansible/roles/*` for hand-rolled `command`/`shell`/`uri` tasks
a maintained collection module could replace outright — real
idempotence and error handling in place of a workaround, at the cost
of a new collection dependency per role that adopts one. Currently
pinned: `community.docker` (5.3.0), `ansible.posix` (2.2.2),
`amazon.aws` (11.4.0), `community.hashi_vault` (7.1.0) — per
`ansible/requirements.yml`.

## Scope

Roles under `ansible/roles/*` whose `command`/`shell`/`uri` tasks a pinned or new
collection module can replace. Not in scope: the tasks Stage 2 reviewed and
found no fit for (`compose`'s volume-filtered `docker ps`, `fwupd`, `telegram_topic_pins`,
the `secrets` role's hex/uuid generation), and the two Stage 3 found no fit for
(`secrets`' own KV read/write status-code branching, `molecule_helpers`'
OpenBao init/unseal/policy/AppRole bootstrap — see Stage 3 below for both).

## Decision

No ADR. Each stage swaps a hand-rolled task for a maintained module with no
contested trade-off; Stage 3 adds a collection dependency, so it opens with a spike (its
exit condition). It runs alongside the Python-side `hvac` work in
[ADR 0030](../decisions/0030-openbao-client-implementation-in-repo-python/revision-000.md).

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | `seaweedfs_bucket` → `amazon.aws.s3_bucket` | Done | the role uses the module; the molecule scenarios pass |
| 2 | Task-shape sweep of the remaining command/shell/uri-heavy roles | Done | every flagged role's tasks reviewed; finds and no-fits recorded below |
| 3 | `secrets` role's AppRole login → `community.hashi_vault.vault_login`; its KV read/write and `molecule_helpers`' OpenBao CLI setup found no fit (see below) | Done | `vault_login.yaml` uses the module; the two no-fits are recorded below |
| 4 | `molecule_helpers`/`openbao`/`step_ca_cert`'s raw `docker run`/`exec` → `community.docker` (already pinned) | Done | the three roles use module equivalents where one exists |
| 5 | `molecule_helpers`'s throwaway cert generation → `community.crypto` | Done | `molecule_helpers` uses the module |
| 6 | `secrets` role's molecule coverage: close the uuid4-generation gap (PR #232's own coverage regression, 97.1 → 93.0) | Done | `rotate_secret` also rotates a uuid4-format secret; `thresholds.yaml`'s `secrets` entry raised to reflect it |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1 — `seaweedfs_bucket` → `amazon.aws`

Done. `amazon.aws.s3_bucket` (9.4.0, pinned in `ansible/requirements.yml`)
replaced the standing `amazon/aws-cli` container +
`docker_container_exec` entirely — confirmed live against a real `weed`
4.46 binary (matching `ghcr.io/chrislusf/seaweedfs:4.46`) running
production's exact `Admin:{{ bucket }}` identity shape: real
create-if-missing idempotence from the module itself (two repeat runs
both `changed: false`), least-privilege scoping still enforced
(`AccessDenied` against an out-of-scope bucket), and no more
`failed_when`/"tolerate already-exists" carve-out needed at all —
an existing bucket is just `changed: false`, not a special-cased
error.

Two things the initial spike (previous revision of this section)
didn't cover, both found by actually building and running the role
rather than stopping at the spike:

- **`storage` itself needs `boto3`/`botocore`.** `amazon.aws.s3_bucket`
  runs on whatever Python interpreter the target host uses, not the
  controller — confirmed live (a boto3-less interpreter fails at
  import time, not with a connectivity/credentials error). The role
  now installs `python3-boto3`/`python3-botocore` via `apt` as its
  first task. Confirmed the other direction too, not just assumed:
  ran the module over a real SSH connection with the *controller*
  process genuinely lacking `boto3` at all (a separate, isolated
  Python with only `ansible-core`) while the target had it —
  succeeded normally. `pyproject.toml` doesn't need `boto3`; nothing
  under `ansible/` imports it directly, and this confirms the module
  itself doesn't need it controller-side either.
- **The retry condition needs to be narrower than "anything but
  success."** Confirmed live that a genuine wrong-credentials request
  against a reachable server returns a normal structured botocore
  error (`response_metadata.http_status_code`) on the first attempt —
  retrying that blindly would have turned the old role's
  fail-fast-on-bad-auth behavior (see the `wrong_credentials` molecule
  scenario) into a ~30s stall before the same eventual failure. The
  task's `until:` now only retries a connection-level failure (no
  `response_metadata` at all) or a real 5xx; any 4xx fails immediately.
  Re-verified the `wrong_credentials` scenario's exact block/rescue
  shape against the real two-task role — `rescued: 1`, one attempt, no
  retry stall.

Molecule: `default` and `wrong_credentials` scenarios needed only
comment updates (no functional changes — both scenarios already just
`include_role: seaweedfs_bucket`). `identity_scoping` needed nothing —
it tests `s3-identity.json.j2` directly via its own aws-cli containers
and never invokes this role at all.

### Stage 2 — sweep results

Every flagged role's actual tasks were read, not just counted:

- **Real finds:** `secrets` role's `read_vault_kv.yaml`/
  `process_vault_secrets.yaml`/`vault_login.yaml` hand-roll
  AppRole login + KV v2 read/write over raw `ansible.builtin.uri` — a
  *third* independent Vault client alongside the two already found in
  Python
  ([`0030-openbao-client-implementation-in-repo-python/revision-000.md`](../decisions/0030-openbao-client-implementation-in-repo-python/revision-000.md)).
  `community.hashi_vault` (built on `hvac`) has native
  `vault_login`/`vault_kv2_get`/`vault_kv2_write` modules that could
  replace all three. `molecule_helpers`' OpenBao test-target setup
  does the same thing again, via `docker exec` + the `bao` CLI, for
  the same reason. Separately, `molecule_helpers`/`openbao`/
  `step_ca_cert` all run raw `docker run`/`exec`/`inspect`/`rm` via
  `command:` for operations `community.docker` — already pinned, and
  already used this way in `seaweedfs_bucket` — covers natively; no new
  dependency, just consistency. `molecule_helpers`' throwaway
  self-signed cert (`openssl req -x509 ...`) is a `community.crypto`
  candidate (new dependency, test-only, low risk).
- **No fit, checked not assumed:** `compose`'s volume-filtered
  `docker ps` query, `fwupd`'s `fwupdmgr` CLI wrapping, and
  `telegram_topic_pins`' chained send-then-pin-by-message-id with
  topic threading. `fwupdmgr` has no known Ansible collection binding;
  the Telegram chain needs the first call's `message_id` for the
  second and a `message_thread_id` a generic notify module doesn't
  expose — staying on raw tasks here is a reviewed decision, not an
  oversight. `secrets` role's `python3 -c` hex/uuid4 generation is a
  minor, low-priority case — an Ansible lookup/filter could drop the
  shell-out, not urgent enough for its own stage yet.

### Stage 3 — `community.hashi_vault`

New collection dependency (7.1.0). The install path that actually
matters is `ansible/requirements.yml` — `ansible-lint`'s pre-push hook,
the CI molecule job's own setup step, and README.md's documented dev
setup (`ansible-galaxy collection install -r ansible/requirements.yml`)
all read it directly. `ansible/roles/molecule_helpers/requirements.yml`
is also kept in sync (same `renovate.json5` `ansible-galaxy-core` group
as `community.docker`/`ansible.posix`/`amazon.aws`) since it's what
`.config/molecule/config.yml`'s `dependency: galaxy` block names — but
checked, not assumed: no scenario's own `test_sequence` (this role's
six included) actually lists a `dependency` step, so that block never
fires during `molecule test` today. Keeping the file in sync is still
correct — matches the existing three collections' own precedent, and
costs nothing if `dependency` is ever wired back in — but installing
the collection is really just the one `ansible-galaxy` command above;
running it again after this stage lands is a normal step, not a sign
either requirements file is wrong.
The version itself is confirmed against the
collection's own `CHANGELOG.rst` release headers, not `galaxy.yml` on
its `main` branch — `main`'s `galaxy.yml` had already been bumped to
`7.2.0` as the in-progress next version before that version was
actually released, which looks identical to a real pin until
`ansible-galaxy` can't find it.
Worth building alongside — not instead of —
[`0030-openbao-client-implementation-in-repo-python/revision-000.md`](../decisions/0030-openbao-client-implementation-in-repo-python/revision-000.md)'s
Python-side `hvac` work, since both are the same underlying client
library (already a `pyproject.toml`/`uv.lock` controller dependency,
`hvac>=2.3`, so this stage needed no new Python package), just two
different calling conventions.

By the time this stage ran, PR #232 had already reshaped the "3 Vault
`uri` tasks" this stage's title used to name: they're now 6, spread
across `vault_login.yaml` (1, the AppRole login), `process_vault_secrets.yaml`
(3, added by that PR's batching), and `read_vault_kv.yaml`/
`rotate-secret.yaml` (1 each, unchanged). The spike answered the
AppRole/custom-CA question for the first of those, and surfaced two
real no-fits for the rest.

**Shipped: `vault_login.yaml`'s AppRole login.** Confirmed live, not
just against the docs — a real OpenBao 2.6.2 binary (built from
GitHub's own release, not Docker, since this spike ran in a sandbox
with no Docker egress) with the actual production `controller.hcl`
policy applied: `community.hashi_vault.vault_login`'s `ca_cert` takes
the exact same plain CA-file path `secrets_vault_ca_tempfile.path`
already is, and returns the token at `login.auth.client_token`. Ran
the two production tasks verbatim (copy-pasted, not reimplemented)
against that real target, then made an independent, separate call with
the resulting token to confirm it actually carries the `controller`
policy — not just that the login call itself returned 200.
`token_validate: false` is deliberate: the module's own default
(`true`) adds a self-lookup call after every login that the raw `uri`
version never made, and that call's own success depends on every
token also carrying Vault's built-in `default` policy for
`lookup-self` — not something `controller.hcl` grants explicitly, so
left off to keep this a like-for-like swap rather than a new implicit
dependency.

The first real `molecule test` run against `vault_backed` (this
sandbox can't run Molecule itself — no Docker egress — so this needed
someone actually running it) caught something the standalone spike
didn't: idempotence failed on this exact task. The module's own
source hardcodes `changed = True` for every non-`token` auth method
("a login is technically a write operation"), on every run,
unconditionally; `ansible.builtin.uri` (the raw call this replaced)
defaults `changed=False` and only sets `True` when writing the
response to a `dest` file, which this task never did — confirmed in
both modules' own source, not assumed, once this surfaced for real.
`changed_when: false` restores the original behavior, same reasoning
the tempfile create/write pair below already documents for the
identical situation. Confirmed on a real re-run of all six of this
role's scenarios afterward: no errors, `vault_backed`'s idempotence
included.

**No fit: `read_vault_kv.yaml` / `process_vault_secrets.yaml`'s KV
read/write.** This role's whole generate-if-missing design leans on
plain HTTP status codes as data (`status_code: [200, 404]` on read,
`[200, 400]` on the racing `cas=0` write) — `vault_kv2_get`/
`vault_kv2_write` don't expose one; they're `hvac` wrappers that raise
and get turned into a `fail_json`. Confirmed live, down to the exact
returned dict, not inferred from source alone:

- A missing secret's `vault_kv2_get` failure `.msg` is a stable,
  distinguishable string (`"Invalid or missing path ['%s'] with secret
  version '%s'. Check the path or secret version."`) — this half is a
  workable swap, checking `'Invalid or missing path' in
  result.msg` rather than a bare `.failed` (which would also swallow a
  real `Forbidden`/permission error into "must not exist yet, generate
  a new one" — a correctness regression today's status-code check
  doesn't have).
- The write side isn't workable the same way. Losing the `cas=0` race
  raises `hvac.exceptions.InvalidRequest: check-and-set parameter did
  not match the current version` — confirmed against the real server —
  but `vault_kv2_write`'s own source discards that text:
  `module.fail_json(msg="InvalidRequest writing to '%s'" % path, ...)`.
  Ran it for real with `failed_when: false`: `.msg` is exactly that
  generic string, no "check-and-set", no `.status`/`412` anywhere. Ran
  it again inside `block`/`rescue` in case `ansible_failed_result`
  preserved more: `.exception` comes back as the literal string
  `"(traceback unavailable)"` on this Ansible version (2.21.4), not the
  traceback it names. There's no way through the module's current
  public interface to tell "lost the create race" apart from any other
  `InvalidRequest`. Left on the raw `uri` tasks, unless a future
  release of the collection exposes this more cleanly — nothing in its
  current changelog suggests one is planned.

**No fit at all: `molecule_helpers`' OpenBao test-target bootstrap**
(`start_openbao_test_target.yaml`'s `docker exec ... bao ...` calls —
init, unseal, enable `kv-v2`/`approle`, write the policy, create the
role, mint `role_id`/`secret_id`). Not a status-code/exception mismatch
this time — confirmed by listing every module the collection ships
(`plugins/modules/` on its `main` branch): it's purely a secrets-access
client (`vault_read`/`vault_write`/`vault_kv1_*`/`vault_kv2_*`/
`vault_database_*`/`vault_pki_generate_certificate`/`vault_login`/
`vault_token_create`). No `operator_init`, `operator_unseal`, or any
`sys/mounts`/`sys/auth` module exists to replace what this bootstrap
does — that's Vault administration, not the secret-consumption surface
this collection covers, so nothing here will ever fit it.

### Stage 4 — `community.docker` consistency pass

No new dependency — already pinned. Turned out less mechanical than
Stage 2's shape-level sweep suggested: read against the collection's
own source at the pinned 5.3.0 tag (`module_utils/_module_container/`
and each module's own `RETURN` docs), not assumed from familiarity
with the general modules, since this sandbox has no Docker to check
any of it live.

**Shipped: `molecule_helpers`' `openbao-test` container lifecycle.**
The old three-task dance (`docker inspect` → decide "already running"
vs "stale" → `docker rm -f` if stale → `docker run -d`) is replaced by
a single `community.docker.docker_container` task with
`state: started`. Confirmed against `present()` in
`module_utils/_module_container/module.py`, not assumed from the
module's docs alone: an existing container is only stopped-and-
recreated when its resolved configuration actually differs from the
task's parameters; otherwise a stopped one is simply started in place
and a running one is left alone — the exact "already running vs stale"
distinction the manual `docker inspect` step existed to make. This also
corrects that step's own comment, which the reading disproves: it
justified the raw `docker inspect` + `from_json` approach on
`docker_container_info`'s `.container.State.*` shape being "unverified
in this repo," but `docker_container_info`'s own `RETURN` doc states
its `container` field "matches the docker inspection output" — the
same JSON `docker inspect` already returns, `State.Running` included.

**Shipped, on reread: every remaining `docker run --rm`/`docker exec`
call that reads command output or passes `BAO_TOKEN` via `-e`.** The
first pass through this stage recorded these as a no-fit (see git
history for that revision); asked to look again, both objections
turned out to have a concrete fix once actually pinned down against
the module source, rather than being genuine dead ends:

- `community.docker.docker_container`'s output capture
  (`container.Output`, with `detach: false` + `cleanup: true` standing
  in for `docker run --rm`) only returns the real command output when
  the container's logging driver is `json-file`, `journald`, or
  `local` — confirmed in `get_container_output()`
  (`module_utils/_module_container/docker_api.py`): any other driver
  returns a placeholder string naming the driver instead of the actual
  output. The fix is to stop depending on the daemon's own default and
  set `log_driver: json-file` explicitly on the task — confirmed as a
  real, ordinary module parameter (`docker_container.py`'s own doc:
  "Docker uses json-file by default"), not a workaround. Applied to
  `openbao/tasks/main.yaml`'s UID read, and to the cert-issuance tasks
  in both `step_ca_cert/tasks/main.yaml` and
  `molecule_helpers/start_openbao_test_target.yaml` (for a clean
  `.msg` on a real failure, even though those two don't consume
  `Output` directly). The plain chown/chmod tasks that never read
  output didn't need it.
  `community.docker.docker_container`'s own `status != 0` handling
  (confirmed in `container_start()`: cleanup runs and the task is
  failed *after*, in that order) already fails the task automatically
  on a non-zero exit, the same as `ansible.builtin.command`'s default —
  no explicit `failed_when` needed on any of these.
- `community.docker.docker_container_exec`'s `env:` parameter is passed
  straight through as the `Env` field of the same Docker Exec-create
  API call the `-e` CLI flag itself populates (confirmed in
  `docker_container_exec.py`) — the identical mechanism, not an
  approximation, so the "unexercised module parameter" objection
  doesn't hold once actually read. The real gap this reading found
  instead: unlike `ansible.builtin.command`, this module never fails
  the task itself on a non-zero `rc` — confirmed in its own source, it
  always calls `exit_json()`, success or not (the same hardcoded-result
  pattern Stage 3 already found in `vault_login`). Every converted task
  now sets `failed_when: <result>.rc != 0` explicitly to keep the
  original fail-on-error behavior. One more difference worth flagging:
  `docker_container_exec`'s `strip_empty_ends` default (`true`) trims
  the trailing newline `bao read`'s output otherwise has, which the raw
  `docker exec` version didn't do — noted inline on "Read the AppRole's
  role_id", since it changes the exact bytes written to
  `molecule_helpers_openbao_role_id_dest`.

Neither of these needed a live daemon to resolve — both were resolved
by reading the collection's own source at the pinned tag, the same
evidence standard Stage 3 already used for its own no-fits.

Confirmed live: every `secrets` and `step_ca_cert` Molecule scenario
run for real, coverage thresholds held at 95.3 and 100.0 respectively
— unchanged from `ansible/molecule-coverage/thresholds.yaml`'s own
pinned values, so this stage's conversions caused no regression.
`step_ca_cert`'s `signal_chown` scenario is the one that actually
exercises `openbao/tasks/main.yaml`'s two converted tasks (it's the
only scenario anywhere that runs that role at all — see the role's own
molecule-testing.md entry) as well as this role's own cert-issuance/
chown-back conversion; `secrets`' `vault_backed`/`rotate_secret`
scenarios cover `molecule_helpers/start_openbao_test_target.yaml`'s
conversions.

### Stage 5 — `community.crypto` for test certs

New dependency, test-only blast radius (`molecule_helpers`'s throwaway
self-signed cert). Lowest priority of the five.

`start_lldap_test_target.yaml`'s single `openssl req -x509 ...`
`command` task is now three `community.crypto` tasks — key, CSR, cert —
rather than a single `openssl_csr_pipe` + in-memory `csr_content` call,
because `x509_certificate`'s own idempotence check only compares
against an *existing file* at `csr_path`; the pipe form has no existing
state to compare against and reports changed on every run, which would
have broken the `idempotence` step both real callers' `molecule.yml`
`test_sequence` already run — `lldap_bootstrap` and `tinyauth`, which
both actually `include_role`/`tasks_from: start_lldap_test_target.yaml`.
Not `tinyauth_ca_trust` or `step_ca_cert`: both were miscounted as
callers in an earlier revision of this note, caught on reread — they
only *mention* this file in a comment. `tinyauth_ca_trust`'s own
converge.yml says so explicitly ("Deliberately NOT
start_lldap_test_target.yaml's openssl self-signed fixture"), and
`step_ca_cert`'s host_vars deploys the real `docker/lldap/compose.yaml`
instead. Confirmed the target genuinely needs
`python3-cryptography` first, the same shape of per-target dependency
Stage 1 found for `boto3`/`botocore` — this role runs with
`become: true` against the molecule instance itself (not `localhost`),
so `community.crypto` needs the library on that Python interpreter, not
the controller's. `selfsigned_not_after: +1d` recomputes relative to
"now" on every run, but `x509_certificate`'s `ignore_timestamps`
defaults to `true` — confirmed against
`module_utils/_crypto/module_backends/certificate.py`'s
`needs_regeneration()` at the pinned 3.4.0 tag, not assumed from the
option's doc string — so that recomputation doesn't force a
regeneration on the idempotence run, unlike Stage 3's `vault_login`
(which hardcodes `changed=True` and needed `changed_when: false`
instead).

Version pinned against `community.crypto`'s own `CHANGELOG.rst` release
headers (latest entry: `v3.4.0`), not `galaxy.yml` on its `main`
branch — same caution Stage 3 already applied to
`community.hashi_vault`: `main`'s `galaxy.yml` is at `3.5.0`, but no
`3.5.0` tag exists yet (confirmed against the tag itself, not just the
changelog), which looks identical to a real pin until `ansible-galaxy`
can't find it.

**Confirmed live, not just from source.** This sandbox has no Docker,
so the three new tasks themselves were first proven with
`ansible-playbook` against real `localhost` instead, run verbatim
(copied out of the real task file, not reimplemented) twice in a row:
the first run produced a real 2048-bit RSA key, a CSR with `subject:
[["CN", "lldap.molecule.test"]]` and `subjectAltName:
["DNS:lldap.molecule.test"]` exactly matching what the old
`-subj`/`-addext` flags asked for, and a cert with
`notBefore`/`notAfter` one calendar day apart; the second run against
the same files reported `changed=0` across all three tasks — the
`ignore_timestamps` reasoning above confirmed as real behavior, not
just read from source.

Since then, `lldap_bootstrap`'s actual `molecule test` — real Docker,
real `idempotence` step, the full scenario this stage's task shape is
built around — has been run for real and reported no issues. `tinyauth`
(the only other real caller, same task file, same vars shape) hasn't
been independently re-run; low risk given it exercises the identical
code path, but still open, not assumed.

### Stage 6 — `secrets` role molecule coverage (PR #232 regression)

PR #232 (flattening `resolve_vault_generated_secret.yaml` into the
batched `process_vault_secrets.yaml`) dropped `secrets`' own
coverage threshold from 97.1 to 93.0. Read against the real coverage
report (not guessed from the diff): three tasks account for the whole
gap, out of 43 total —

- `Re-read after losing a create race` and `Index Vault re-read
  results by secret name` (`process_vault_secrets.yaml:258`/`274`) —
  only exercised by two genuinely concurrent writers racing the same
  `cas=0` create. **Deliberately not pursued**: the only non-flaky way
  to trigger a real Vault CAS conflict here is two Molecule platform
  hosts both running the role against the same shared `vault_scope`
  secret — reproducing the exact mechanism `main.yaml`'s own header
  comment already documents ("runs once per host, each delegating to
  localhost") — and that was weighed and set aside as not worth
  building for this project. Accepted, permanent gap, not a no-fit
  awaiting a future fix like Stage 3's two below it.
- `Generate a fresh uuid4 value in memory` (`generate_vault_value.yaml:29`)
  — its `when:` (`format == 'uuid4'`) was never satisfied by any
  scenario. `rotate_secret` is the only caller of this file at all
  (confirmed by the coverage report itself — every other scenario
  shows `never_observed` on both of its generate tasks), and its own
  fixture only ever rotated a hex-format secret.

Fixed: `rotate_secret`'s `secrets_registry` gained a second,
uuid4-format entry (`secrets-molecule-rotate-uuid4-example`), and its
converge now runs the real `rotate-secret.yaml` playbook a second time
(Play 2c) against it — same real playbook, not a reimplementation,
just a different `secret_name`. `verify.yml` asserts the same four
things the existing hex checks do: the value actually changed, the new
value is a real UUID4, Vault's own KV version incremented by exactly
one, and that version is genuinely `> 1` (an update, not a create).

Verified the specific new code path live, not just read — this
sandbox has no Docker, so the full scenario's own DinD platform and
step-ca sibling couldn't run here, but the two tasks that actually
changed (`generate_vault_value.yaml`'s uuid4 branch, and the
`cas=<version>` write) were run verbatim against a real OpenBao target
seeded with a real uuid4 secret: the hex task correctly skipped, the
uuid4 task fired and produced a real UUID4, the write succeeded, and
Vault's own KV version went 1 → 2. `thresholds.yaml`'s `secrets` entry
raised to 95.3 (41/43) accordingly — worth confirming against a real
`molecule test` run, which needs Docker this sandbox doesn't have.

## Acceptance criteria

- [ ] No hand-rolled `command`/`shell`/`uri` task remains in `ansible/roles/*` where a maintained module fits; the rest are recorded under Stage 2 or Stage 3 as reviewed no-fits.
- [ ] Every new collection is pinned in `ansible/requirements.yml`.
- [ ] The molecule scenarios pass for every role touched.

## Risks

**Not confirmed, and can't be from a dev sandbox**: the exact failure
shape for a real HTTP 502 arriving *through Caddy*
(`offsite_backup_s3_proto`/`offsite_backup_s3_endpoint`) during
SeaweedFS's actual cold start — every retry-condition test here talked
to SeaweedFS directly, never through a real Caddy reverse proxy. The
`until:` condition is written to retry any non-2xx/4xx outcome
generally (which should cover a proxy 502), but whether Caddy's own
error page produces a botocore response shape this condition still
correctly matches needs a live check on `storage` after this first
deploys — worth a deliberate first-deploy watch, not assumed safe.

- `community.hashi_vault` may not handle the custom-CA verify pattern the raw `uri` tasks use today; Stage 3's spike answers it before any task is swapped.

## Open items

- If `amazon.aws.s3_bucket` (Stage 1) and `boto3` (via
  [`0046-python-client-for-s3-compatible-storage/revision-000.md`](../decisions/0046-python-client-for-s3-compatible-storage/revision-000.md))
  both land, `boto3` becomes a real `pyproject.toml` dependency for the
  first time via that other stage, not this one — Stage 1 confirmed
  live that it doesn't need `boto3` controller-side at all (see Stage 1
  detail above), so there's no existing entry for that stage to reuse
  or collide with.
- ~~`docker`/`compose_app` aren't flagged here...~~ Resolved: checked
  both roles' `tasks/` directly — neither has any `command`/`shell`/
  `uri` task at all. `docker` is `apt`/`file`/`get_url`/
  `deb822_repository`/`systemd`/`user` only; `compose_app` only
  dispatches into `compose` (already Stage 2's own finding) via
  `include_role`. Nothing here for this project to do.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] The linked revision is `accepted`, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
