# Caddy: Reverse Proxy & TLS

The `caddy` role runs on **every** host in the inventory, giving each host its own reverse proxy fronting only the apps it locally runs.

## Custom image

Caddy's DNS-01 challenge support for DigitalOcean isn't in the stock image, so the role generates a `Dockerfile` that uses `xcaddy` to build Caddy with the `github.com/caddy-dns/digitalocean` plugin, then builds it locally before every deploy. The app's `compose.yaml` sets `pull_policy: never` so it always runs that locally-built image rather than trying to pull one.

## Caddyfile generation

`Caddyfile.j2` is rendered from the host's resolved `compose_apps` and covers three concerns:

1. A global `cert_issuer acme` block using the DigitalOcean DNS provider and public DNS resolvers, so every site block can get certificates via DNS-01 (no port 80/443 exposure required to a CA).
2. A reusable `tinyauth_forwarder` snippet — a `forward_auth` call to Tinyauth's `/api/auth/caddy` endpoint that forwards the original host/proto/URI and copies back the `Remote-*` identity headers. If the host runs Tinyauth itself, its own top-level domain block is rendered first (it isn't part of the wildcard vhost below, since it *is* the auth provider).
3. A single wildcard vhost, `*.{{ caddy_domain }}`, containing one `handle` block per routable app (anything with a `caddy` key in its resolved registry entry). Each handle matches on `host {{ route.host }}.{{ caddy_domain }}`, optionally imports the `tinyauth_forwarder` snippet (route-level `auth` defaults to `true`; some apps like Cobalt opt out), then reverse-proxies to that app's `upstream`. Anything that doesn't match falls through to a `403 Access Denied` responder.

## Deploy ordering

Config generation, image build, and deploy/restart all happen in Play 2 of `deploy.yaml`, before any backend app container exists — the `compose_app_extra_changed` flag is set from whether the Caddyfile actually changed, so Caddy is force-restarted on config changes even when Docker Compose itself sees no diff (the image tag doesn't change between builds).

## Runtime config

`docker/caddy/compose.yaml`: exposes `80/tcp`, `443/tcp`, and `443/udp` (HTTP/3), mounts the rendered `Caddyfile` plus persistent `data`/`config` volumes for certificates and state, and joins a dedicated `caddy-proxy` Docker network. Tagged `diun.enable=false` since it's rebuilt/managed by Ansible rather than watched for upstream image updates.
