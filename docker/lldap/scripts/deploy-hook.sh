#!/bin/sh
# certbot --deploy-hook, run by entrypoint.sh after any issue/renewal.
#
# certbot and lldap are separate containers with no shared cert volume, so:
#   1. Copy the renewed cert/key out of certbot's Let's Encrypt live dir
#      into ./certs (bind-mounted into lldap at /data/certs — see
#      docker/lldap/compose.yaml).
#   2. Restart lldap via restart-lldap.py so it picks up the new files —
#      lldap does not hot-reload TLS certs on change. The restart goes
#      through the `dockerproxy` service (a locked-down Docker socket
#      proxy) rather than mounting the real socket into this container.

LIVE_DIR="/etc/letsencrypt/live/${LDAP_DOMAIN}"
OUT_DIR="/output-certs"
cp -L "${LIVE_DIR}/fullchain.pem" "${OUT_DIR}/fullchain.pem"
cp -L "${LIVE_DIR}/privkey.pem"   "${OUT_DIR}/privkey.pem"

if [ -S /var/run/docker.sock ]; then
  python3 /scripts/restart-lldap.py
else
  echo "[deploy-hook] WARNING: /var/run/docker.sock not mounted - restart lldap manually"
fi
