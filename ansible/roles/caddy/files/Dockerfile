FROM caddy:2.11.4-builder AS builder
RUN xcaddy build --with github.com/caddy-dns/digitalocean

FROM caddy:2.11.4
RUN apk add --no-cache curl
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
