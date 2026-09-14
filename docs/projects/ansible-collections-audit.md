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
pinned: `community.docker` (5.3.0), `ansible.posix` (2.2.2) — per
`ansible/requirements.yml`. No decision draft yet; this doc's own Stage
2 *is* the not-yet-done audit.

## Stages

| # | Stage | Status |
| :-: | :--- | :--- |
| 1 | `seaweedfs_bucket` → `amazon.aws.s3_bucket` | In progress |
| 2 | Task-shape sweep of the remaining command/shell/uri-heavy roles | Done |
| 3 | `secrets` role's 3 Vault `uri` tasks + `molecule_helpers`' OpenBao CLI setup → `community.hashi_vault` | Not started |
| 4 | `molecule_helpers`/`openbao`/`step_ca_cert`'s raw `docker run`/`exec` → `community.docker` (already pinned) | Not started |
| 5 | `molecule_helpers`'s throwaway cert generation → `community.crypto` | Not started |

## Stage detail

### Stage 1 — `seaweedfs_bucket` → `amazon.aws`

Confirmed concretely: the role keeps a standing `amazon/aws-cli:2.36.43`
container alive (`community.docker.docker_container`,
`state: started`) specifically because, per the task's own comment,
"there's no way to make an ephemeral container idempotent short of not
recreating it," then execs `aws s3 mb` inside it
(`community.docker.docker_container_exec`) with a retry-on-502 for
SeaweedFS's cold-start behavior. `amazon.aws.s3_bucket`, pointed at the
same `endpoint_url`, is a plausible direct replacement — real
idempotence from the module itself, no standing container needed at
all. Not yet a dependency: `amazon.aws` isn't in `ansible/requirements.yml`
today (only `community.docker`/`ansible.posix` are).

Spike done: `amazon.aws.s3_bucket` (collection 9.4.0) against a real
`weed` 4.46 binary (the same version `ghcr.io/chrislusf/seaweedfs:4.46`
pins) — the module's own docs list DigitalOcean/Ceph/Walrus/FakeS3/
StorageGRID as its tested non-AWS targets and state the collection is
otherwise "only tested against AWS," so SeaweedFS was worth checking
rather than assuming.

- **Bucket lifecycle works cleanly.** `state: present` against a
  bucket scoped with production's exact `Admin:{{ bucket }}` identity
  shape (`docker/seaweedfs/configs/s3-identity.json.j2`) created the
  bucket and read back versioning/ownership/public-access-block/
  encryption/tags without error on the first call.
- **Real idempotence, confirmed** — two subsequent runs against the
  same bucket both reported `changed: false`. This is the actual gap
  the current role's standing-container workaround exists to paper
  over, closed for free by the module.
- **Least-privilege scoping still enforced** — a request against a
  bucket this identity has no `Admin:` grant for came back
  `AccessDenied`, same as production's per-identity model expects.
- **Does not solve the cold-start-502 problem on its own.** The module
  has no `wait`/`retry` option (checked its full option list). A
  connection-level failure surfaces as `failed: true` with a clean
  `msg` field ("Invalid endpoint provided: Could not connect to the
  endpoint URL...") — a better `until:`/`failed_when:` match target
  than the current task's raw stdout/stderr grep, but the replacement
  task still needs the same `until:`/`retries:`/`delay:` wrapper the
  current one has, just matching `msg` instead. **Not confirmed**: the
  actual failure shape for a real HTTP 502 arriving *through Caddy*
  (`offsite_backup_s3_proto`/`offsite_backup_s3_endpoint`) — this spike
  only reproduced a direct connection-refused case (no Caddy in the
  loop), so the exact `until:` condition needs a live check against
  `storage`'s real endpoint before it's finalized, not assumed from
  this result.

Implementation (rewriting the role, updating
`ansible/requirements.yml` and the three molecule scenarios) is next;
not yet started.

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
  both land, `boto3` becomes a real dependency in two unrelated parts
  of this repo — worth knowing going in, not discovering by accident.
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
