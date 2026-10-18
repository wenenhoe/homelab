---
id: ADR-0087
revision: 0
type: adr
title: Delivering files that Ansible renders to a container
short: Ansible-rendered files in containers
solution: Read-only bind mounts from the stack directory; volumes only for state the app writes
summary: Where a file Ansible renders for a container lives, so a config file needs no volume of its own.
topic: deployment-platform
status: working
narrows: ADR-0005
---

# 0087. Delivering files that Ansible renders to a container

Narrows [ADR 0005 (Persistent container state)](../0005-persistent-container-state-and-host-permissions/revision-000.md)
on one point: its Decision moves *persistent app state* to named volumes, and
this revision stops that rule reaching files Ansible renders and the container
only reads. State the app writes stays in a volume, as ADR 0005 decided.

## Problem

A container needs files that Ansible renders or copies from the repo: a
reverse-proxy config, an entrypoint script, a service's configuration, a
credentials file. The file has to reach the container, stay correct when the
repo changes, and not be mistaken for state the app owns.

## Context

ADR 0005 chose named volumes for two reasons: a container's UID has to match
the owner of a host directory it writes, and the backup agent works on volumes.
Neither reason applies to a file the container only reads:

- A read-only file needs to be readable by the container's user, not owned by
  it. The seed step copies with `cp -a`, so a file in a volume already has the
  owner and mode of its staged copy on the host; a bind mount of that same file
  has the same owner and mode.
- A rendered file is derived from the repo and inventory, so it is rebuilt by a
  deploy and has no place in a backup.

Putting such a file in a volume costs a volume, a staging tree, a throwaway seed
container per change and, for a single file, a `subpath` mount that needs Docker
Engine 25 and Compose 2.22. A volume that mixes a seeded file with app-written
state also has to be reseeded by hand after a reset
([`volume-maintenance.md`](../../topics/deploy/volume-maintenance.md)).

A bind mount of a file behaves in two ways a volume does not:

- **A replaced file is not seen by a running container.** Ansible's `template`
  and `copy` replace a file by renaming a new one over it. A container that
  mounted the old file keeps reading it until the container restarts, and
  Compose does not recreate a service whose bind-mounted file changed.
- **A file bind-mounted inside a named volume's directory leaves an empty file
  at that path in the volume.** It stays after the container is removed, so it
  appears in the volume's backup and in a restore.

## Decision

- A file or directory that Ansible renders or copies from the repo, that the
  container only reads, and that nothing in the container writes beside, is
  bind-mounted `:ro` from the app's stack directory. It does not go in a volume.
- State the app writes, and any directory the app writes beside a file Ansible
  placed, stays in a named volume ([ADR 0005](../0005-persistent-container-state-and-host-permissions/revision-000.md)).
- A bind-mounted file is never mounted inside a volume's directory. It is mounted
  at a path outside every volume, moving the app's config path there where the
  app allows it. Where it does not, the file stays seeded into its volume.
- A change to a bind-mounted file restarts the container that mounts it in the
  same deploy run. How the deploy detects the change is left to the
  implementation.
- The owner and mode of a bind-mounted file are set in its catalog entry, as for
  any direct config. A file that carries a secret keeps `no_log` and a mode
  that excludes other users.
- Host resources, the Docker socket, stay bind mounts as before.

## Alternatives considered

- **Keep every Ansible-rendered file in a volume.** Rejected: it is the cost
  listed in Context for a property the file does not need.
- **Bind-mount app state too.** Rejected for the reasons in ADR 0005, which still
  hold: the UID match, and a backup agent that works on volumes.
- **Mount a file inside the app's volume directory.** Rejected: it leaves a
  placeholder in the volume, so the volume's backup carries a file the app does
  not own.

## Consequences

The compose role's change detection covers seeded volumes only, so it must learn
to cover a changed bind-mounted file. A running host keeps the volumes this
revision makes unnecessary until they are removed, and the cleanup playbook keeps
a stale volume by default ([`cleanup.md`](../../topics/deploy/cleanup.md)).
[`volumes.md`](../../topics/deploy/volumes.md) describes what stays a bind mount
and changes with the implementation.

## Invariants

- Nothing a container writes lives in a bind mount from the stack directory.
- A file mounted from the stack directory is read-only in the container.
- Every bind-mounted file can be rebuilt from the repo and inventory alone.
- After a deploy that changed a bind-mounted file, the container that mounts it
  reads the new content.

## Non-goals

- Certificates and keys a role renews or rotates at runtime.
- A directory that holds both a file Ansible placed and a file the app writes.
- Moving any state the app writes out of a volume.
- Volumes' own `subpath` mounts of a directory the app writes, such as a shared
  world directory.

## Validation

A Molecule scenario changes a bind-mounted file, deploys, and asserts that the
container restarted and reads the new content, and that a second run changes
nothing.

## Reconsideration triggers

A bind-mounted file turns out to need an owner the deploy user cannot give it
without a privilege the container otherwise lacks.
