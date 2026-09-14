---
id: PROJ-ansible-collections-audit
title: "Ansible Roles: Native Collection Module Audit"
type: project
status: in-progress
summary: "Audit `ansible/roles/*` for hand-rolled command/shell/uri tasks a native collection module could replace — `seaweedfs_bucket` → `amazon.aws.s3_bucket` confirmed as the first candidate."
---

# Ansible Roles: Native Collection Module Audit

**Status:** In progress

Sweeps `ansible/roles/*` for hand-rolled `command`/`shell`/`uri` tasks
a maintained collection module could replace outright — real
idempotence and error handling in place of a workaround, at the cost
of a new collection dependency per role that adopts one. Currently
pinned: `community.docker` (5.3.0), `ansible.posix` (2.2.2),
`amazon.aws` (9.4.0) — per `ansible/requirements.yml`. No decision
draft yet; this doc's own Stage 2 *is* the not-yet-done audit.

## Stages

| # | Stage | Status |
| :-: | :--- | :--- |
| 1 | `seaweedfs_bucket` → `amazon.aws.s3_bucket` | Done |
| 2 | Task-shape sweep of the remaining command/shell/uri-heavy roles | Done |
| 3 | `secrets` role's 3 Vault `uri` tasks + `molecule_helpers`' OpenBao CLI setup → `community.hashi_vault` | Not started |
| 4 | `molecule_helpers`/`openbao`/`step_ca_cert`'s raw `docker run`/`exec` → `community.docker` (already pinned) | Not started |
| 5 | `molecule_helpers`'s throwaway cert generation → `community.crypto` | Not started |

## Stage detail

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

Molecule: `default` and `wrong_credentials` scenarios needed only
comment updates (no functional changes — both scenarios already just
`include_role: seaweedfs_bucket`). `identity_scoping` needed nothing —
it tests `s3-identity.json.j2` directly via its own aws-cli containers
and never invokes this role at all.

### Stage 2 — sweep results

Every flagged role's actual tasks were read, not just counted:

- **Real finds:** `secrets` role's `read_vault_kv.yaml`/
  `resolve_vault_generated_secret.yaml`/`vault_login.yaml` hand-roll
  AppRole login + KV v2 read/write over raw `ansible.builtin.uri` — a
  *third* independent Vault client alongside the two already found in
  Python
  ([`openbao-client-hvac-paramiko-adoption.md`](../decisions/drafts/openbao-client-hvac-paramiko-adoption.md)).
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

New collection dependency. Covers `secrets` role's 3 production Vault
tasks and `molecule_helpers`' test-side OpenBao setup. Worth building
alongside — not instead of —
[`openbao-client-hvac-paramiko-adoption.md`](../decisions/drafts/openbao-client-hvac-paramiko-adoption.md)'s
Python-side `hvac` work, since both are the same underlying client
library, just two different calling conventions (Ansible module vs.
Python import). Needs a spike: does `community.hashi_vault`'s AppRole
login handle the same custom-CA-verify pattern
(`secrets_vault_ca_tempfile`) the raw `uri` tasks do today.

### Stage 4 — `community.docker` consistency pass

No new dependency — already pinned. Mechanical: replace raw
`command: [docker, ...]` with `community.docker.docker_container`/
`docker_container_exec`/`docker_image_info` where a direct module
equivalent exists, in `molecule_helpers`, `openbao`, and
`step_ca_cert`.

### Stage 5 — `community.crypto` for test certs

New dependency, test-only blast radius (`molecule_helpers`'s throwaway
self-signed cert). Lowest priority of the five.

## Open items

- If `amazon.aws.s3_bucket` (Stage 1) and `boto3` (via
  [`rclone-boto3-scope-not-blanket-swap.md`](../decisions/drafts/rclone-boto3-scope-not-blanket-swap.md))
  both land, `boto3` becomes a real `pyproject.toml` dependency for the
  first time via that other stage, not this one — Stage 1 confirmed
  live that it doesn't need `boto3` controller-side at all (see Stage 1
  detail above), so there's no existing entry for that stage to reuse
  or collide with.
- `docker`/`compose_app` aren't flagged here since `community.docker`
  is already pinned and likely already covers them — confirm during
  Stage 2 rather than assume.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes) — run
before deleting this doc once every stage is Done.

- [ ] Every `Done` stage's rationale exists as a real ADR, or plainly
      didn't need one.
- [ ] Every `Done` stage's current behavior is in a topic doc.
- [ ] Every open item is resolved-and-promoted or moved to where it
      belongs next.
- [ ] Every cross-reference into this doc elsewhere in the repo is
      updated or removed.
