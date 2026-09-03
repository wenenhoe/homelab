# 0008. Use Caddy, not Nginx Proxy Manager

**Status:** Accepted

## Context

The very first reverse-proxy setup (`feat: Add caddy reverse proxy for
play server`, June 16) used Nginx Proxy Manager (npm) for every other
service host. npm's routes, TLS config, and access rules are configured
through its own web UI, backed by its own database — there is no
config file to check into this repo. That's incompatible with this
repo's core premise (see the main [`README.md`](../../README.md)):
every host's config is generated and converged by Ansible, with no
manual step beyond `ansible-playbook`. An npm-fronted host's actual
routing config exists only in that host's npm database, invisible to
git, to code review, and to Ansible.

## Decision

Replace npm with Caddy everywhere, configured entirely through a
`Caddyfile` (later templated via Jinja — see
[`caddy.md`](../caddy.md)) checked into this repo like every other
config.

## Consequences

Every route, TLS issuer, and access rule is now version-controlled,
diffable in a PR, and reproducible from a fresh host with no manual
UI setup — the same property this repo already wanted for everything
else. The cost: no web UI for ad hoc changes; every new route is a
`Caddyfile`/`app_registry` change and a redeploy, not a few clicks.
That's the trade this repo consistently makes elsewhere too (see
[`adding-an-app.md`](../adding-an-app.md)).
