# Caddy: Reverse Proxy & TLS

The `caddy` role runs on **every** host in the inventory, giving each host its own reverse proxy fronting only the apps it locally runs.

## Custom image

Caddy's DNS-01 challenge support for DigitalOcean isn't in the stock image, so the role generates a `Dockerfile` that uses `xcaddy` to build Caddy with the `github.com/caddy-dns/digitalocean` plugin, then builds it locally. The app's `compose.yaml` sets `pull_policy: never` so it always runs that locally-built image rather than trying to pull one.

The build itself only happens when it needs to: on a host where the image doesn't exist yet (first deploy), or whenever `ansible-playbook deploy.yaml --tags images` is run explicitly. A normal full run on an already-provisioned host leaves the existing image alone rather than paying for a full `nocache` rebuild every time — see the [Tags section in `deployment-flow.md`](deployment-flow.md#tags) for the `images`/`infra` split.

## Caddyfile generation

`Caddyfile.j2` is rendered from the host's resolved `compose_apps` and covers three concerns:

1. A global `cert_issuer acme` block using the DigitalOcean DNS provider and public DNS resolvers, so every site block can get certificates via DNS-01 (no port 80/443 exposure required to a CA).
2. A reusable `tinyauth_forwarder` snippet — a `forward_auth` call to Tinyauth's `/api/auth/caddy` endpoint that forwards the original host/proto/URI and copies back the `Remote-*` identity headers. If the host runs Tinyauth itself, its own top-level domain block is rendered first (it isn't part of the wildcard vhost below, since it *is* the auth provider).
3. A single wildcard vhost, `*.{{ caddy_domain }}`, containing one `handle` block per routable app (anything with a `caddy` key in its resolved registry entry). Each handle matches on `host {{ route.host }}.{{ caddy_domain }}`, optionally imports the `tinyauth_forwarder` snippet (route-level `auth` defaults to `true`; some apps like Cobalt opt out), then reverse-proxies to that app's `upstream`. Anything that doesn't match falls through to a `403 Access Denied` responder.

## Deploy ordering

Config generation, image build, and deploy/restart all happen in Play 2 of `deploy.yaml`, before any backend app container exists. `caddy_config_changes.changed` (from rendering the Caddyfile to a staging path) both decides whether to seed the `caddyfile` volume and, passed on as `compose_app_extra_changed`, forces a restart specifically for Caddyfile-only changes — the kind of change Docker Compose has no way to detect on its own, since nothing about the compose file or image changed. A rebuilt local image *is* picked up automatically by the regular `docker_compose_v2: state: present` deploy step, without needing this flag: Compose compares the image ID a running container was created from against the currently-tagged image, not just the tag itself, so a same-tag rebuild still triggers a recreate. See [`volumes.md`](volumes.md) for how the Caddyfile seeding step works.

## Runtime config

`docker/caddy/compose.yaml`: exposes `80/tcp`, `443/tcp`, and `443/udp` (HTTP/3), joins a dedicated `caddy-proxy` Docker network, and mounts three named Docker volumes: `caddyfile` (the rendered `Caddyfile`, mounted via Compose's `volume.subpath` syntax since it's a single file, not the whole volume) plus `data`/`config` for certificates and Caddy's own admin-API state. Tagged `diun.enable=false` since it's rebuilt/managed by Ansible rather than watched for upstream image updates.
