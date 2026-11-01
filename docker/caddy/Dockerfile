FROM caddy:2.11.7-builder@sha256:c4cd20eaa0b69112fd5d4f721ffc9671687e1d5d0b155c8620cf7546dbef94c0 AS builder
RUN xcaddy build --with github.com/caddy-dns/digitalocean

FROM caddy:2.11.7@sha256:36c24ad91a7ff7bc4c87fe22bfa8df3c4b18da0773d73fc12ee2c52b98c0bb7e
# hadolint ignore=DL3018 # curl is for compose.yaml's healthcheck exec; alpine package versions aren't Renovate-tracked here.
RUN apk add --no-cache curl
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
