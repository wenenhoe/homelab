FROM caddy:2.11.7-builder@sha256:c2fc374fd352439d76e1777b28d97d9f6d9c1dd86116db9227460374d46097d5 AS builder
RUN xcaddy build --with github.com/caddy-dns/digitalocean

FROM caddy:2.11.7@sha256:504a44d7d74bd2bc28a66afc4774912fc21223ca8a67734af1c54ab2f999b489
# hadolint ignore=DL3018 # curl is for compose.yaml's healthcheck exec; alpine package versions aren't Renovate-tracked here.
RUN apk add --no-cache curl
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
