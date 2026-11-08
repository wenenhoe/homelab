# Caddy: Service Record

The reverse proxy and TLS terminator that runs on every managed host and fronts only the apps that host runs. The Caddyfile generation, the custom image and the expiry alerting are in [`caddy.md`](../services/caddy.md); the catalog's facts are in the [coverage table](../disaster-recovery/coverage.md).

## Dependencies

- Needs the `caddy-proxy` network, the `caddyfile`, `data` and `config` volumes, and the DigitalOcean DNS credential in its `.env` (from OpenBao) for the DNS-01 certificate challenge. The image is built in this repository with the DigitalOcean plugin.
- Needs `tinyauth` for every route that does not set `auth: false`: it calls Tinyauth's forward-auth endpoint ([`caddy.md`](../services/caddy.md#caddyfile-generation)).
- Needed by every app with a route, and by the operator's access to the dashboards.

## Data

- Certificates and the ACME account in the `data` volume; the rendered Caddyfile in `caddyfile`. Certificate private keys and the DNS credential are secrets.

## Exposure

- Ports 80 and 443 (TCP) and 443 (UDP, HTTP/3) are published on every interface of each host. It is the only listener most apps have.
- A wildcard virtual host serves `*.{{ caddy_domain }}` and returns 403 for any host name no route matches ([`caddy.md`](../services/caddy.md#caddyfile-generation)).
- Outbound, it calls the DNS provider's API and the certificate authority. It keeps `NET_BIND_SERVICE` only ([`adding-an-app.md`](../deploy/adding-an-app.md#container-hardening)).
- Which routes skip Tinyauth is a catalog decision and is shown in the [coverage table](../disaster-recovery/coverage.md).

## Threat model

- A route without `auth: false` is protected only if Tinyauth answers; a route that opts out relies on the app's own authentication. A mistaken opt-out exposes the app, which is why the coverage table lists each route's authentication.
- The DNS credential can edit the zone. It sits in the host's `.env` at mode `0600`. Unknown: how narrowly the DigitalOcean token is scoped; check the token in the provider's console.
- The wildcard certificate means one key covers every service name on that host.

## Observability

- The container health check and Beszel report its state ([`beszel.md`](../monitoring/beszel.md)).
- `caddy_cert_expiry` checks that the live certificate is not near expiry and pushes a daily `cert-expiry-*` heartbeat, with a Telegram alert on failure ([`caddy.md`](../services/caddy.md#cert-expiry-alerting), [`gatus.md`](../monitoring/gatus.md)).

## Disaster recovery

Not backed up; recovery tier 3. The Caddyfile is rendered from the repository and certificates are issued again by DNS-01, so a redeploy rebuilds it. Unknown: whether a rebuild of several hosts at once could hit the certificate authority's issuance limits; check the provider's published limits. Acceptable loss and downtime: Unknown; check [`exercises.md`](../disaster-recovery/exercises.md).

## Lifecycle

- Upgrade: bump the Caddy version in the Dockerfile, let the image workflow build it, then bump the pinned tag ([`caddy.md`](../services/caddy.md#custom-image)).
- Removal: removes access to every app on the host.
- Waits on `tinyauth` for gated routes; it deploys first on each host so backends can register behind it ([`caddy.md`](../services/caddy.md#deploy-ordering)).
