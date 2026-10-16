# Docker Daemon Configuration

`/etc/docker/daemon.json` on every managed host. The `docker` role
(`ansible/roles/docker/tasks/daemon_config.yaml`) merges
`docker_daemon_defaults` (`ansible/roles/docker/defaults/main.yaml`) into it
in Play 1 of `deploy.yaml`; see [`deployment-flow.md`](deployment-flow.md).

## Defaults

| Setting | Effect |
| :--- | :--- |
| `no-new-privileges` | Every container starts with the kernel's `no_new_privs` flag set, so `exec` cannot grant it a privilege through a setuid binary. A service opts out with `security_opt: [no-new-privileges=false]`. Existing containers keep what they were created with until they are recreated. `cap_drop` has no daemon-wide default (`dockerd` rejects `default-cap-drop`), so it stays per service; see [Container hardening](adding-an-app.md#container-hardening). |
| `log-driver`, `log-opts` | Every container's `json-file` log rotates at the size and file count in `docker_daemon_defaults`, so one noisy container cannot fill the VM disk. A container's own `logging:` block in its compose file overrides the daemon default. |

A daemon default applies to containers created after Docker restarts. A
container keeps the logging it was created with until it is recreated, so
an existing app changes when its compose project recreates it, not when
the daemon restarts.

## One file, two roles

The `bind9` role merges its own `dns` key into the same file
([`bind9.md`](../services/bind9.md#self-managed-deploy-ordering)). Both roles
read the file, add their keys and write it back, so neither removes the
other's keys, and a key set by hand outside both survives. They write the
same bytes for the same content (sorted keys, `to_nice_json`, no trailing
newline, mode `0644`). A different format in either role makes each rewrite
the other's output on every run and restart Docker twice per deploy.

The `docker` role checks the merged file with `dockerd --validate` before
it replaces the old one. `dockerd` will not start on a key it does not
recognise, so a typo fails the task and leaves the working file in place.

## Restarts

A change to the file restarts Docker through the `Restart docker` handler,
at the end of the play. Every container on the host stops and comes back
under its restart policy. The first rollout of a new default restarts each
host that already runs apps; later runs change nothing.

`live-restore` is not enabled. Docker supports it only across patch
releases of the same minor version
([Docker's live restore page](https://docs.docker.com/engine/daemon/live-restore/)),
and `maintenance.yaml` upgrades every installed package, Docker included,
so a host can skip minor versions between runs. Docker then cannot
reattach to the running containers, and they must be stopped by hand.

## Verifying a host

```sh
sudo cat /etc/docker/daemon.json
docker inspect --format '{{json .HostConfig.LogConfig}}' <container>
docker info --format '{{.SecurityOptions}}'
```

`docker info` lists `name=no-new-privileges` once the default is on.
`docker inspect` does not show it in a container's `SecurityOpt`; read
`NoNewPrivs` in `/proc/<pid>/status` on the host instead.

The file holds the role's keys alongside `dns` on the DNS host. A container
created after the restart shows the default `Config`; one created before it
shows an empty `Config` until it is recreated. The role's Molecule scenario
asserts the same property on a fresh container and that a key it does not
own survives; see [`molecule-testing.md`](../engineering/molecule-testing.md).
