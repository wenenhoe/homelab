#!/bin/sh
# Entrypoint for the `certbot` service in docker/lldap/compose.yaml.
#
# lldap has no built-in ACME client and doesn't hot-reload certs on file
# change (see deploy-hook.sh), so this container owns the cert lifecycle
# for LDAPS on its behalf:
#   1. Write the DigitalOcean API token to a credentials file certbot's
#      dns-digitalocean plugin can read (skipped if already present, so
#      re-creating the container doesn't require the token again).
#   2. Issue a cert via DNS-01 (DigitalOcean plugin) on first run only, if
#      `/etc/letsencrypt/live/${LDAP_DOMAIN}` doesn't already exist.
#      --deploy-hook runs deploy-hook.sh, which copies the cert where
#      lldap reads it from and restarts the lldap container to pick it up.
#   3. Loop `certbot renew` every 12h for the lifetime of the container;
#      renewal re-runs the same deploy hook only when a cert actually
#      renews.
#
# Expects LDAP_DOMAIN, LETSENCRYPT_EMAIL, DO_API_TOKEN in the environment
# (from docker/lldap/configs/env.j2).
set -e

DO_API_TOKEN_FILE="/creds/digitalocean.ini"

if [ ! -f "$DO_API_TOKEN_FILE" ]; then
    printf "%s\n" "dns_digitalocean_token = ${DO_API_TOKEN}" > "$DO_API_TOKEN_FILE";
    chmod 600 "$DO_API_TOKEN_FILE";
fi

if [ ! -d /etc/letsencrypt/live/${LDAP_DOMAIN} ]; then
    certbot certonly --non-interactive --agree-tos --email ${LETSENCRYPT_EMAIL} \
        --dns-digitalocean \
        --dns-digitalocean-credentials ${DO_API_TOKEN_FILE} \
        --dns-digitalocean-propagation-seconds 60 \
        --domain ${LDAP_DOMAIN} \
        --deploy-hook /scripts/deploy-hook.sh;
fi

trap exit TERM
while :; do
    certbot renew --non-interactive --quiet;
    sleep 12h & wait;
done
