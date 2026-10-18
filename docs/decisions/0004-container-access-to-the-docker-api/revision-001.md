---
id: ADR-0004
revision: 1
type: adr
title: Container access to the Docker API
short: Docker API access
solution: A proxy rules file per consumer that names the exact calls it makes, mounted into the stock docker-socket-proxy image
summary: Containers that need the Docker API get only the calls they make, so a consumer that stops and starts containers cannot also create or run them.
topic: deployment-platform
status: working
supersedes: 0
related: [ADR-0009, ADR-0043, ADR-0083]
---

# 0004. Docker API access by the calls a consumer makes

## Context

[Revision 0](revision-000.md) puts every Docker API consumer behind a
`docker-socket-proxy` sidecar and scopes each by capability flags such as
`CONTAINERS=1`. That is right for a consumer that only reads. It leaves a
gap for one that has to write.

How the proxy's flags work, from its `haproxy.cfg` at the pinned v0.5.0
(the image is `haproxy:3.4.2-alpine` with that file as a template):

- `POST` is a single switch. With `POST=0`, the frontend's first rule
  refuses every method but `GET` and `HEAD`, before any other rule runs,
  so the `ALLOW_START`, `ALLOW_STOP` and `ALLOW_RESTARTS` flags can never
  admit a write. They only narrow a `POST=1`.
- Every other flag, `CONTAINERS` among them, admits a path family with
  **any** method the first rule let through. With `POST=1` and
  `CONTAINERS=1`, a `POST` to `/containers/create`, to
  `/containers/{id}/exec` or to `/containers/{id}/kill` is allowed as well as
  the start and stop that was wanted. The same `CONTAINERS=1` with `POST=0`
  also admits `GET` on `/containers/{id}/json`, `/logs` and `/archive`, which
  reveal a container's environment, output and files.
- So no combination of flags allows start and stop of a container and
  nothing else.

`backup_agent` is the one consumer with a write grant
(`CONTAINERS=1 POST=1 INFO=1`,
[`compose.yaml.j2`](../../../ansible/roles/backup_agent/templates/compose.yaml.j2)).
Its need is narrow. `docker-volume-backup` v2.49.1 makes these calls
around a snapshot, read from its source (`stop_restart.go`, `script.go`):

| Call | Why |
| :--- | :--- |
| `HEAD`/`GET /_ping` | API version negotiation when the client starts |
| `GET /info` | whether the daemon is a swarm manager |
| `GET /containers/json` | the running containers: once for the stop labels, matched in the client, and once for each phase's `-pre` and `-post` exec label, matched by a `filters` query |
| `POST /containers/{id}/stop` | stop each container the schedule's label names |
| `POST /containers/{id}/start` | start it again afterwards |

It calls `/exec` only for a container carrying a
`docker-volume-backup.<phase>-pre` or `-post` label, which no app here sets,
and `/services` only on a swarm manager, which no host is. The client uses the
container's full 64-character id from the list, never its name.

A refused call can leave an app stopped only if it is the `start`. The
`archive-pre` step runs before the stop, and the restart is deferred inside the
archive step, so it runs on every error path and before `archive-post`.

What the proxy still cannot do is limit *which* container is stopped. It
has no per-container rule, and an id is not known ahead of time, so
[`backup.md`](../../topics/disaster-recovery/backup.md#whats-backed-up)'s
note that the grant reaches any container on the host stands.

**Threat model.** Adversary: code running in a proxied consumer, through a
compromised image or dependency. Asset: the host and the other containers'
data. The Docker API can run a new container with a host path bound into it,
or an exec in an existing one, and either is root on the host. Attack path:
the consumer's own network access to its proxy, which is the whole grant the
proxy exists to bound. The rules below make that grant the consumer's actual
calls.

## Decision

Give the proxy a rules file of its own for each consumer that writes, naming
the exact method and path of every call it makes, and refuse everything else.
Mount it over the image's template, `/usr/local/etc/haproxy/haproxy.cfg.template`.
The entrypoint only substitutes `${BIND_CONFIG}` into that file and starts
HAProxy, so the stock image, its pin and Renovate's bumps of it stay as they
are, and nothing is built.

For `backup_agent` the frontend is:

```haproxy
frontend dockerfrontend
    bind ${BIND_CONFIG}
    http-request allow if METH_GET { path,url_dec -m reg ^(/v[\d\.]+)?/((_ping)|(version)|(info)|(containers/json))$ }
    http-request allow if { method POST } { path,url_dec -m reg ^(/v[\d\.]+)?/containers/[a-f0-9]{64}/((start)|(stop))$ }
    http-request deny
    default_backend dockerbackend
```

The rest of the file is the upstream file unchanged (global, defaults and the
`dockerbackend`), and the `docker-events` backend is dropped, because nothing
allowed reaches it. `/version` stays only because the sidecar's healthcheck
requests it. The `CONTAINERS`, `POST` and `INFO` environment lines go, since
the rules no longer read them.

Tried against HAProxy 3.4.0 built with PCRE2, as the official image is, and a
fake Docker socket that records what reaches it: the five calls above pass and
arrive at the socket unchanged, with and without a `/v1.xx` prefix or a query
string. Each of these is refused with a 403 and never reaches it: `POST
/containers/create`, `/exec`, `/kill`, `/restart`, `/update`, `/pause`,
`/rename`, `/attach`; `DELETE /containers/{id}`; `GET /containers/{id}/json`,
`/logs`, `/archive`, `/export`; `GET /events`, `/images`, `/volumes`; `POST
/exec/{id}/start` and `/build`; a `GET` of the stop or start path and a `POST`
of `/containers/json`; a start or stop by container name, by a 63-character id
or by an upper-case id; a path with a trailing segment or slash, a leading `//`,
and `/containers/json/../{id}/archive` or `/v1.xx/../containers/json`. A
URL-encoded `/containers/%6Ason` decodes to the allowed path and is passed on,
which is the same resource.

The consumer that only reads (`beszel-agent`) keeps its flags in this
revision; see Consequences.

## Alternatives considered

- **Keep the flags and the documented limit.** The limit documented in revision
  0 is that any container can be stopped. It omits create and exec, which the
  flags admit as well, and which are far more than the consumer needs.
- **`POST=0` with `ALLOW_START` and `ALLOW_STOP`.** Refused by the rule order
  above, and `CONTAINERS=1` would still be needed to list.
- **A custom image.** It would carry the same rules file, plus a build, a
  registry and a second pin to keep current. The file alone is enough, and an
  image becomes worth it only if a consumer needs something a rules file cannot
  express.
- **A different proxy with per-method allow-lists.** It would change the shared
  pattern for every consumer, to get what one file in the current image already
  gives.
- **No Docker API: stop and start the app from the host.** That moves the
  stop and start out of the backup agent's schedule, which is the point of its
  per-schedule labels.

## Assumptions

- **Claim:** the pinned image, HAProxy 3.4.2 on Alpine, loads and applies this
  file as HAProxy 3.4.0 built with PCRE2 did, and the real
  `docker-volume-backup` v2.49.1 image completes a stop-during-backup run
  through it.
  **Breaks if wrong:** a stop-during-backup schedule fails against the real
  image, or the agent gets a 403 for the `start` after stopping an app and
  leaves it stopped.
  **Checked by:** the `backup_agent` Molecule scenario, run against the real
  proxy image and the real agent image with a stop-during-backup schedule, which
  asserts the app stopped, was backed up and started, and that a `create` and an
  `exec` through the proxy are refused.

## Consequences

- A compromised `backup_agent` can still stop and start any container by id
  and can list every container with its labels, which is what the existing
  limit says. It can no longer create, exec into, kill, update or delete
  containers, read their environment, files or logs, or reach any other
  endpoint.
- The rules file is a copy of upstream's with one frontend replaced. A bump of
  the proxy image can change the parts copied, so a Renovate pull request for
  it is reviewed against upstream's `haproxy.cfg` at the new tag and run
  through the Molecule scenario above, which is the check that the file still
  loads.
- A new call by `docker-volume-backup` after a version bump fails with a 403.
  The same Molecule scenario runs on a bump of that image.
- A container labelled `docker-volume-backup.<phase>-pre` or `-post` makes the
  agent ask for an exec, which the rules refuse, so every backup schedule on
  that host fails. The `archive-pre` step runs before anything is stopped, so
  nothing is left stopped. No app here sets one.
- [`backup.md`](../../topics/disaster-recovery/backup.md) and revision 0's
  consequences name `POST=1` as the grant. They change to describe the rules file
  when it lands.
- `beszel-agent` uses `CONTAINERS=1` with `POST=0`, so it cannot write, but the
  same flag admits reading a container's environment, files and logs. Its needs
  differ from `backup_agent`'s, so it is a separate change that applies this
  mechanism with a file per consumer, not part of this revision.

## Invariants

- No proxy that has a write grant reads capability flags for it. Its rules file
  names each method and path.
- A rules file ends in `http-request deny`.
- A write rule matches a container by its full id and one verb, never a path
  family.
- The real socket is mounted only into a proxy, read-only.

## Validation

- A test that renders the rules file, runs HAProxy against a fake socket and
  asserts the allowed calls arrive and each refused call from the list above
  gets a 403, so the file is checked without Docker.
- The `backup_agent` Molecule scenario above, on the real images.

## Reconsideration triggers

- A consumer needs a call a rules file cannot express, such as a per-container
  rule.
- `docker-volume-backup` or the proxy image changes the calls or the file layout.
- An app needs one of the agent's exec labels, which the rules refuse by design.

## Revision notes

`diun` is removed from the consumers this revision leaves on capability flags:
[ADR 0083 (Images a deploy runs)](../0083-making-a-deploy-run-the-images-its-commit-names/revision-000.md)
retires it, and its proxy sidecar goes with it. Revision 0 still describes it as
it was when that revision was written.
