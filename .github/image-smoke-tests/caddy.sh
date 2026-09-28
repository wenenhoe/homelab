#!/usr/bin/env bash
# Smoke test for docker/caddy/Dockerfile: the two things it exists to add
# to the stock image — the DigitalOcean DNS module, and curl for
# compose.yaml's healthcheck. Usage: caddy.sh <image>
set -euo pipefail

image="$1"

docker run --rm "$image" caddy list-modules | grep -q 'dns.providers.digitalocean'
docker run --rm "$image" curl --version
