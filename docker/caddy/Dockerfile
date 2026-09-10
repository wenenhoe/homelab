FROM caddy:2.11.4-builder AS builder
RUN xcaddy build --with github.com/caddy-dns/digitalocean

FROM caddy:2.11.4
# hadolint ignore=DL3018 # curl is for compose.yaml's healthcheck exec; alpine package versions aren't Renovate-tracked here.
RUN apk add --no-cache curl
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
