FROM caddy:2.11.7-builder@sha256:bf6a7d38add2508b7d2e3e3f40cf2af399214f143c0fa3daa51f254e01f8d293 AS builder
RUN xcaddy build --with github.com/caddy-dns/digitalocean

FROM caddy:2.11.7@sha256:5e5286cb37d44086d651a5363f05f43a692ce4d649d88fb1bd844579f45fa9e8
# hadolint ignore=DL3018 # curl is for compose.yaml's healthcheck exec; alpine package versions aren't Renovate-tracked here.
RUN apk add --no-cache curl
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
