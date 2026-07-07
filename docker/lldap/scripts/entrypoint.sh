#!/bin/sh
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
