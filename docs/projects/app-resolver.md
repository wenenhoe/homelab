---
id: PROJ-app-resolver
title: "App Resolver"
type: project
status: building
blocked: false
summary: "A pure resolve_apps filter builds resolved_apps; every consumer reads it, and app_registry becomes app_catalog."
decision: ADR-0065/0
---

# App Resolver

Replaces the `set_fact` merge in `compose/tasks/preinit.yaml` with a pure
filter that every role can read the result of, for any host, and renames
the data it reads. Staged because the plugin path must be proven before
anything depends on it, and because the renames touch most of the repo.

## Scope

The resolver filter and its plugin directory, `resolved_apps`, a catalog
validator, the consumers that read the catalog or re-include `preinit.yaml`,
and the `app_registry` → `app_catalog` and `caddy:` → `routes:` renames.
Not in scope: the secret catalog, changes to what any catalog
entry says, and other filters (see Open items).

## Decision

Implements
[ADR 0065](../decisions/0065-where-app-defaults-and-host-intent-are-merged/revision-000.md),
`approved` once stage 1 resolved its assumptions.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Spike: repo-level plugin directory and lazy `resolved_apps` | Done | A trivial filter loads from one `ansible-playbook` run and one Molecule scenario, and `restore_discovery`'s play reads another host's `resolved_apps`; ADR 0065's first two assumptions are resolved |
| 2 | `resolve_apps` filter with unit tests | Done | The filter's output equals `preinit.yaml`'s for every app on every host in the inventory; pytest covers dict merge and list replacement |
| 3 | Catalog validator | Not started | Runs in pre-commit and CI against the real catalog; unique names, `backup.volumes` within `volumes`, and route upstreams are checked |
| 4 | Move consumers to `resolved_apps` | Not started | `cloud_sync` and `restore_discovery` no longer read the catalog; `compose_apps` is never reassigned; `ci_boot_test`, `volume-reset`, `cleanup` and the Molecule helper no longer include `preinit.yaml` for the merge |
| 5 | Renames | Not started | `app_registry` is `app_catalog` and `caddy:` is `routes:` everywhere, including docs, `AGENTS.md` and Molecule fixtures; only the resolver's call site names `app_catalog`, checked by a test |

Stage status is `Not started`, `In progress`, or `Done`. Stage 5 is
mechanical and ships as separate pull requests for the variable and file
and for the route key.

## Acceptance criteria

- [ ] `resolved_apps` is the only app list any role or playbook reads for
      a resolved definition.
- [ ] The resolver's output matches the previous merge for every app.
- [ ] The filter and the validator have unit tests that run in CI.
- [ ] The Molecule scenarios and `pre-commit run --all-files` pass.

## Risks

- The rename touches 88 files and can conflict with other open work. Do it
  when few branches are in flight.
- `combine(recursive=True)` replaces lists. A filter that merged lists
  instead would change deployed configs. No host overrides a catalog list
  today, so the inventory equality test cannot see that drift; the filter's
  unit tests pin the behaviour instead.

## Open items

- Whether the shared default for `backup.extra_cloud_targets`, spelled out
  separately in `cloud_sync` and `restore_discovery`, joins the resolver or
  becomes its own filter.
- Other pure Jinja transformations can become filters in
  `ansible/filter_plugins/`, as `cron_period_hours` and the
  direct-versus-seeded classification in `compose/tasks/init.yaml`
  (`app_deploy_plan`) already have. Each is scoped when it is taken on, not
  here.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] Every bullet of the linked revision's Decision is implemented, or named by a successor project.
- [ ] The linked revision is `accepted`, another project still names it, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
