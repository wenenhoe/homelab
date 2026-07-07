#!/bin/sh
# Restart lldap via the Docker API over the mounted socket so it loads the
# new certificate (lldap does not hot-reload TLS certs on file change).

LIVE_DIR="/etc/letsencrypt/live/${LDAP_DOMAIN}"
OUT_DIR="/output-certs"
cp -L "${LIVE_DIR}/fullchain.pem" "${OUT_DIR}/fullchain.pem"
cp -L "${LIVE_DIR}/privkey.pem"   "${OUT_DIR}/privkey.pem"

if [ -S /var/run/docker.sock ]; then
  python3 /scripts/restart-lldap.py
else
  echo "[deploy-hook] WARNING: /var/run/docker.sock not mounted - restart lldap manually"
fi
