#!/usr/bin/env bash
# CI-only: seeds a self-signed cert into lldap's two cert-related volumes
# before boot, used by _compose-boot-test.yml for the lldap matrix entry
# only. See docs/ci.md#compose-boot-test for why this exists.
#
# docker/lldap/scripts/entrypoint.sh only calls `certbot certonly` when
# /etc/letsencrypt/live/<LDAP_DOMAIN> doesn't already exist, so seeding
# that path (inside the letsencrypt_conf volume) makes certbot skip
# straight to its `certbot renew` loop — no real DNS-01 call. Seeding the
# certs volume separately gives the lldap service itself real cert files
# to load. Neither container's code is touched.
#
# Usage: seed-lldap-ci-cert.sh <path-to-seeded-lldap/.env>
set -euo pipefail

env_file="$1"
ldap_domain=$(grep '^LDAP_DOMAIN=' "$env_file" | cut -d= -f2-)
[ -n "$ldap_domain" ] || { echo "::error::LDAP_DOMAIN not found in $env_file"; exit 1; }

workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT

openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
  -keyout "$workdir/privkey.pem" -out "$workdir/fullchain.pem" \
  -subj "/CN=${ldap_domain}" -addext "subjectAltName=DNS:${ldap_domain}"

docker run --rm -v lldap_certs:/out -v "$workdir:/in:ro" alpine \
  cp /in/fullchain.pem /in/privkey.pem /out/

docker run --rm -v lldap_letsencrypt_conf:/etc/letsencrypt -v "$workdir:/in:ro" alpine \
  sh -c "mkdir -p '/etc/letsencrypt/live/${ldap_domain}' && cp /in/fullchain.pem /in/privkey.pem '/etc/letsencrypt/live/${ldap_domain}/'"
