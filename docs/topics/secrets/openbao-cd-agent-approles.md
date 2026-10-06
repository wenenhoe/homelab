# OpenBao's CD agent AppRoles

Four AppRoles, one per category of unattended work on `cd_agent`, each
bound to that host's fixed address. See
[ADR 0020 revision 1](../../decisions/0020-automation-identity-and-access-scope/revision-001.md)
for why there are four and what each is meant to be unable to reach.

The policies are checked in under
[`docker/openbao/policies/`](../../../docker/openbao/policies/). The roles
are created by hand through `vault-bootstrap` (below), the same way
[`openbao-auth.md`](openbao-auth.md) creates `controller`'s role: nothing
in Ansible creates them.

## The policies

| Role | Policy | Can | Cannot |
| :--- | :--- | :--- | :--- |
| `cd-agent-deploy` | [`cd-agent-deploy.hcl`](../../../docker/openbao/policies/cd-agent-deploy.hcl) | Read `hosts/*` and `cloud_credentials/leaf/*`; create a `hosts/*` path that does not exist yet. | Update an existing `hosts/*` path; touch `cloud_credentials/rotation/*`; write any leaf. |
| `cd-agent-rotation` | [`cd-agent-rotation.hcl`](../../../docker/openbao/policies/cd-agent-rotation.hcl) | Read, create and update `cloud_credentials/leaf/*` and `cloud_credentials/rotation/*`. | Read or write anything under `hosts/*`. |
| `cd-agent-freshness` | [`cd-agent-freshness.hcl`](../../../docker/openbao/policies/cd-agent-freshness.hcl) | Read `cloud_credentials/leaf/*`, `cloud_credentials/rotation/*` and `hosts/all/telegram/*`. | Create or update any path. |
| `cd-agent-snapshot` | [`cd-agent-snapshot.hcl`](../../../docker/openbao/policies/cd-agent-snapshot.hcl) | Save a raft snapshot; read the six leaf paths `snapshot-push.sh` reads. | Read any other leaf, any rotation-tier path, or anything under `hosts/*`; write any path. |

All paths are KV v2 data paths under `secret/data/`. Every `Cannot` above
was confirmed against a real OpenBao 2.7.0 with these exact policy files.

## Creating the roles

`cd_agent` needs its fixed address first: it is the value of both CIDR
binds. From a `vault-bootstrap` session
([`openbao-vault-bootstrap.md`](openbao-vault-bootstrap.md)), with the four
`.hcl` files copied to `/tmp` on `security` first:

```sh
cd_agent_ip=<cd_agent's fixed LAN IP>
for job in deploy rotation freshness snapshot; do
  bao policy write "cd-agent-$job" - < "/tmp/cd-agent-$job.hcl"
  bao write "auth/approle/role/cd-agent-$job" \
    token_policies="cd-agent-$job" \
    token_ttl=1h token_max_ttl=1h \
    secret_id_ttl=0 secret_id_num_uses=0 \
    secret_id_bound_cidrs="$cd_agent_ip/32" \
    token_bound_cidrs="$cd_agent_ip/32"
done
```

- **`token_ttl`/`token_max_ttl` 1h, non-renewable.** The agent's default
  job timeout is `1h` (`cd_agent_default_timeout`,
  [`cd-agent-host.md`](../deploy/cd-agent-host.md)), so a token outlives a
  run that finishes in time and no longer. Each job logs in fresh per
  invocation. A job given a longer `timeout` needs its role's TTL raised
  to match.
- **`secret_id_ttl=0`, `secret_id_num_uses=0`.** The `secret_id` never
  expires and is reusable, since the host logs in on every run. The CIDR
  bind and the narrow policies limit what a leaked one can do.
- **Both CIDR binds.** `secret_id_bound_cidrs` stops a `secret_id` from
  logging in from any other address; `token_bound_cidrs` stops a token from
  being used from one. Each was confirmed to refuse a second source address.

Read a role back to check it:

```sh
bao read auth/approle/role/cd-agent-deploy
```

`secret_id_bound_cidrs` shows `<ip>/32`, but `token_bound_cidrs` shows the
bare `<ip>`: OpenBao normalizes a single-host range. They are the same
binding.

## Handing over a `secret_id`

Each `secret_id` is requested response-wrapped, so the value never appears
in the response that carries it:

```sh
bao write -wrap-ttl=5m -f -field=wrapping_token \
  auth/approle/role/cd-agent-deploy/secret-id
```

The wrapping token is sent to `cd_agent` as a remote command's stdin, never
as an argument ([ADR 0047](../../decisions/0047-first-credential-bootstrap-for-automated-processes/revision-000.md)),
and unwrapped once there. `bao unwrap` with no token argument uses
`BAO_TOKEN` as the wrapping token, so the token is read from stdin into a
child shell's environment:

```sh
IFS= read -r BAO_TOKEN; export BAO_TOKEN; bao unwrap -field=secret_id
```

The first unwrap prints the `secret_id` (no trailing newline when stdout is
not a terminal) and it logs in from the bound address. A second unwrap of
the same token fails with `wrapping token is not valid or does not exist`,
so an intercepted token shows up as a failure, not a quietly reusable
credential. The value lands in the job's credentials directory,
`/etc/cd-agent/credentials/<job>/`, as `openbao-controller-secret-id`, a
`0400` file owned by the job's user `cd-agent-<job>`; the role creates that
directory and no file in it ([`cd-agent-host.md`](../deploy/cd-agent-host.md)).

## What a job reads from its credentials directory

The job's unit sets `HOMELAB_SECRETS_DIR` to its credentials directory, and
the file cache the `secrets` role and `tools/utils/repo.py` read from moves
there: a job logs in to OpenBao with `openbao-controller-role-id` and
`openbao-controller-secret-id`, and resolves the OpenBao address from
`main-domain`, all in that directory. The variable must be an absolute path;
unset, the cache stays `ansible/files/secrets/` in the checkout, which is
what an operator's own runs use. The role's `role_id` is not secret, but it
sits beside the `secret_id` so one directory holds everything a login needs.

## The root cert a job verifies OpenBao against

A job holds no SSH key to `security`, so it cannot fetch step-ca's root cert
the way an operator's run does ([ADR 0022
revision 1](../../decisions/0022-controller-trust-in-the-secrets-store-tls/revision-001.md)).
The root is public, so it is delivered as a plain file, `step-ca-root.crt`,
next to the AppRole files in each job's credentials directory, with the same
owner and no wrapped handoff. Read it from `security`:

```sh
docker exec step-ca cat /home/step/certs/root_ca.crt
```

`cloud_credentials` verifies OpenBao against that file when it exists and
fetches from `security` otherwise. A file that is not a PEM certificate stops
the run with a message naming it, and nothing falls back to skipping
verification.

A run of the `secrets` role that has both a delivered copy and a root freshly
fetched from `security` (the Ansible deploy path) fails, naming the file, when
the two differ. Only a copy such a run holds is compared; the other jobs'
copies are found stale only when their TLS verification fails.

When step-ca's root changes, deliver the new `root_ca.crt` to every job's
credentials directory, then run a job that can compare, which confirms the
copies it holds match.

A role holds any number of independent `secret_id`s, each unwrapped to its
own file. `redeploy-storage`, the rotation job's successor
([ADR 0074](../../decisions/0074-following-one-automation-job-with-another-under-a-different-identity/revision-000.md)),
runs as its own user with a second `secret_id` of `cd-agent-deploy`, so
that role needs no extra policy for it: request one more wrapped
`secret_id` for it the same way.

## A lost create race fails the deploy run

The secrets play writes a generated secret with `cas=0`, which OpenBao
authorizes as `create` only while the path does not exist. If another writer
creates the same path first, the second write is an update, and
`cd-agent-deploy` has no `update`: OpenBao answers **403**, not the 400 that
[`process_vault_secrets.yaml`](../../../ansible/roles/secrets/tasks/process_vault_secrets.yaml)
treats as "lost the race, re-read". The run fails; the next run reads the
value that now exists and proceeds. Accepting 403 there would also swallow
real permission errors, so the play is left as it is.

## Changing `cd_agent`'s address

Every role's two CIDR binds need updating by an operator. A job must never
do it: it would be editing its own trust boundary.
