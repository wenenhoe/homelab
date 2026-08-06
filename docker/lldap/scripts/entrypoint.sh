#!/bin/sh
# Entrypoint for the `certbot` service in docker/lldap/compose.yaml.
#
# lldap has no built-in ACME client and doesn't hot-reload certs (see
# deploy-hook.sh), so this container owns the LDAPS cert lifecycle: writes
# the DigitalOcean token for certbot's dns-digitalocean plugin, issues a
# cert via DNS-01 on first run (--deploy-hook copies it where lldap reads
# it from and restarts lldap to pick it up), then loops `certbot renew`
# every 12h for the container's lifetime.
#
# Expects LDAP_DOMAIN, LETSENCRYPT_EMAIL, DO_API_TOKEN in the environment.
set -e

# /etc/letsencrypt is a named volume (no host path to bind-mount the hook
# from), so place it here ourselves on every start instead — cheap and
# idempotent.
mkdir -p /etc/letsencrypt/renewal-hooks/deploy
cp /scripts/deploy-hook.sh /etc/letsencrypt/renewal-hooks/deploy/deploy-hook.sh
chmod +x /etc/letsencrypt/renewal-hooks/deploy/deploy-hook.sh

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
