FROM caddy:2.11.9-builder@sha256:345264d8c6b50f44f4a4d507d4e6b6bcae40eef2f210d70f76e717fd8cc31baf AS builder
RUN xcaddy build --with github.com/caddy-dns/digitalocean

FROM caddy:2.11.9@sha256:e40b94d0a43b5ff69cb20568d73f10c70703df7b0ffc2298eb3d723cdc9d0bd1
# hadolint ignore=DL3018 # curl is for compose.yaml's healthcheck exec; alpine package versions aren't Renovate-tracked here.
RUN apk add --no-cache curl
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
