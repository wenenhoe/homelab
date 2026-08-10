# Caddy: Reverse Proxy & TLS

The `caddy` role runs on **every** host in the inventory, giving each host its own reverse proxy fronting only the apps it locally runs.

## Custom image

Caddy's DNS-01 challenge support for DigitalOcean isn't in the stock image, so the role copies a static `Dockerfile` (`ansible/roles/caddy/files/Dockerfile`) that uses `xcaddy` to build Caddy with the `github.com/caddy-dns/digitalocean` plugin, then builds it locally. The app's `compose.yaml` sets `pull_policy: never` so it always runs that locally-built image rather than trying to pull one.

The build only runs when the image doesn't exist yet, or when `--tags
images` is passed explicitly — a normal full run on an already-provisioned
host leaves the existing image alone. See the [Tags section in
`deployment-flow.md`](deployment-flow.md#tags).

Since the image is never pulled from a registry, `diun` can't watch it
the normal way (the running container's tag, `caddy-digitalocean:v1.0`,
never changes). Instead `diun` watches the generated Dockerfile for
upstream `caddy:builder`/`caddy:latest` changes — see
[`docker/diun/compose.yaml`](../docker/diun/compose.yaml)'s dockerfile
provider config.

## Caddyfile generation

`Caddyfile.j2` is rendered from the host's resolved `compose_apps` and covers three concerns:

1. A global `cert_issuer acme` block using the DigitalOcean DNS provider
   and public DNS resolvers, so certs come via DNS-01 (no port 80/443
   exposure to a CA required).
2. A reusable `tinyauth_forwarder` snippet — `forward_auth` to Tinyauth's
   `/api/auth/caddy`, forwarding host/proto/URI and copying back the
   `Remote-*` identity headers. If the host runs Tinyauth itself, its own
   domain block renders first (outside the wildcard vhost, since it *is*
   the auth provider).
3. A single wildcard vhost, `*.{{ caddy_domain }}`, with one `handle`
   block per routable app. Each matches `host {{ route.host
   }}.{{ caddy_domain }}`, optionally imports `tinyauth_forwarder`
   (`auth` defaults to `true`; some apps like Cobalt opt out), then
   reverse-proxies to `upstream`. Unmatched requests get `403 Access
   Denied`.

## Deploy ordering

Config generation, image build, and deploy/restart happen in Play 2,
before any backend app exists. `caddy_config_changes.changed` decides
whether to seed the `caddyfile` volume and forces a restart for
Caddyfile-only changes (via `compose_app_extra_changed`) — the kind of
change Compose can't detect on its own. A rebuilt image is picked up
automatically by the regular deploy step, since Compose compares image
ID, not tag. See [`volumes.md`](volumes.md).

## Runtime config

`docker/caddy/compose.yaml`: exposes `80/tcp`, `443/tcp`, `443/udp`
(HTTP/3), joins the `caddy-proxy` network, mounts `caddyfile` (single
file via `volume.subpath`) plus `data`/`config` for certs and admin-API
state. Tagged `diun.enable=false` — its tag is managed by Ansible, not
`diun`'s Docker provider (see [Custom image](#custom-image)).
