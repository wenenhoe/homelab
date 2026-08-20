# Molecule Fixtures

A scenario's `files/docker/<app>/` is read directly off disk by
`compose_source_dir` (an Ansible controller-side path, not a Docker build
context), so a fixture can be a symlink and nothing downstream needs to
know — with one gotcha: `ansible.builtin.find`'s default `file_type`
never matches a symlink, even with `follow: true` (verified — that
option only affects recursion/stat-following, not this classification).
`compose/tasks/init.yaml`'s `find` for `compose*.yaml`/`Dockerfile*`
sets `file_type: any` because of this; any other `find`-based discovery
added later over a fixture directory needs the same.

## Apps with a real prod counterpart

`caddy`, `lldap`, `bind9`, and `tinyauth` symlink their compose file and
any `configs/*.j2` straight at `docker/<app>/` instead of keeping a
hand-copied duplicate. `bind9` symlinks `compose.yaml.j2` specifically
(see [`adding-an-app.md`](adding-an-app.md) for the `.j2` convention) —
it inlines `server_timezone` directly rather than carrying a separate
`.env`, so there's no `configs/env.j2` to symlink alongside it anymore.
This is stronger than keeping the two in sync by convention: Renovate
ignores symlinks outright, so a version-bump PR touches the one real
file, and the same test run that exercises the role exercises prod's
actual compose file — there's no separate fixture pin left to drift.

## `app_registry` entries

For scenarios that carry their own local copy (molecule never loads the
real inventory, so `host_vars/*.yaml` or `converge.yml`'s play `vars:`
duplicate the relevant entry rather than reference it — see `bind9`'s
`host_vars` for why it has to be a `host_vars` file specifically, not
play `vars:`), extract from the real registry instead of hand-copying
it:

```yaml
app_registry: >-
  {{
    (lookup('file', playbook_dir ~ '/../../../../inventory/group_vars/all/app_registry.yaml')
     | from_yaml).app_registry
    | combine({'testapp': {}})
  }}
```

`playbook_dir` here resolves to the *scenario's* directory (wherever
`converge.yml` lives), not wherever this expression is written.
`combine()` adds whatever synthetic fixture-only apps the scenario needs
(`testapp` above has no real registry entry to extract). Every scenario
with a real prod counterpart uses this now — `bind9`, `caddy`,
`caddy_cert_expiry`, `lldap_cert` (×2), `tinyauth`, and
`tinyauth_ca_trust`. `caddy_cert_expiry`'s `no_routed_apps` scenario is
the one holdout: its `app_registry` entries are empty stubs on purpose
(the guard it tests fires before that content would ever matter), not a
real duplicate at risk of drift. The remaining synthetic-app scenarios
(`compose`, `compose_app`, `backup_agent`, `restore`, ...) still
hand-copy an `app_registry` and always will — there's no real entry to
extract for a fixture app like `testapp`/`happy_app_a` that doesn't
exist in production.

## Cross-scenario generic fixtures

`configs/env.j2` (`GREETING=hello-from-{{ compose_app_item.name }}`),
`configs/seeded.txt.j2`, and `scripts/run.sh` were byte-identical across
scenarios purely because nothing in them ever referenced a specific app.
These live once under `ansible/roles/molecule_helpers/fixtures/`
(`generic_env.j2`, `generic_seeded.txt.j2`, `generic_run.sh`) and get
symlinked in. `molecule_helpers` is the right home for anything shared
across more than one role — `check_molecule_matrix`
(`.github/scripts/check-doc-drift.py`) excludes it from the scenario
matrix entirely, so nothing role-local has to carry it.

## Synthetic placeholder apps

The `alpine:3.20` / `sleep infinity` fixtures used to test
`compose`/`compose_app`'s batch logic mostly aren't identical to each
other — the volume count, `container_name`, `labels`, and `env_file`
presence *are* what each test is exercising, so keeping those as
distinct static files is clearer than templating one generic shape with
conditionals. Three shapes recur often enough to be worth a shared file
instead, all under `molecule_helpers/fixtures/`:

- `generic_alpine_app/compose.yaml` — no volume, no `container_name`,
  nothing else. No top-level `name:` either: Compose resolves the
  project name from, in order, a `-p` flag, `COMPOSE_PROJECT_NAME`, the
  file's own `name:`, then the containing directory's basename — the
  compose role's deploy calls pass none of the first two, so a fixture
  with no `name:` at all gets its project name from its directory,
  which is already the right value.
- `generic_alpine_app_with_volume/compose.yaml` — same, plus one volume
  mounted at `/data`. The external volume's `name:` uses
  `${COMPOSE_PROJECT_NAME}_data` interpolation instead of a literal
  string — confirmed live (`docker compose config`) that Compose
  exposes its own resolved project name for interpolation within the
  same file, matching what `ensure_volume.yaml` creates on the Ansible
  side. Upstream has an open issue about this being unreliable in some
  cases (`docker/compose#9530`) — if a future Compose version regresses
  it, this file is the first thing to check.
- `generic_alpine_app_with_env_file/compose.yaml` — no volume, plain
  `env_file: [.env]`. Not every app with `env_file` qualifies for this —
  only ones where the rendered `.env` content and its assertions live
  entirely in the *consuming* scenario (its own
  `app_registry`/`verify.yml`), not in the compose file itself.

## Container discovery without `container_name`

Fixtures that used to declare `container_name:` purely so
`verify.yml`/`converge.yml` could look them up by a fixed name
(`happy_app_nostop`, `restore_target`, etc.) now get discovered by
Compose project label instead, since a shared fixture can't carry a
distinct literal name — a `docker_host_info` lookup by
`com.docker.compose.project=<app>` label, feeding the discovered
container ID into `docker_container_info`. See
`ansible/roles/restore/molecule/default/verify.yml` for the pattern to
copy. Deliberately kept as two tasks rather than switching to
`docker_host_info`'s own `verbose_output` container shape — that keeps
the already-proven `.container.State.*` shape from `docker_container_info`
instead of trusting an unverified nested structure for something
version-drift could silently break.
