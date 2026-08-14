#!/usr/bin/env bash
# CI-only: exercises the real lldap_cert issuance path against a
# throwaway step-ca instead of an independently-authored openssl
# self-signed cert, then seeds the result into lldap's `certs` volume —
# used by _compose-boot-test.yml for the lldap matrix entry only. See
# docs/ci.md#compose-boot-test for why this exists.
#
# Deliberately the official smallstep/step-ca image driven by its own
# stock DOCKER_STEPCA_INIT_* auto-init, not docker/step-ca's own
# compose/entrypoint.sh — this is a fully throwaway CA that only needs
# to exist for the length of this job, so the extra machinery that setup
# exists for (separate CA/provisioner passwords, a non-default claim
# duration, persistence across restarts) doesn't apply here. The `step
# ca certificate` call below is the same one lldap_cert's real Ansible
# task runs — same flags, same shape — against this throwaway CA
# instead of production's.
#
# Usage: seed-lldap-ci-cert.sh <caddy-proxy-network-name> <lldap-fqdn>
set -euo pipefail

network="$1"
lldap_fqdn="$2"
ca_password="ci-dummy-step-ca-password"
step_ca_image="smallstep/step-ca:0.30.2"
step_cli_image="smallstep/step-cli:0.30.2"

workdir=$(mktemp -d)
# mktemp -d defaults to 0700 — smallstep/step-cli runs as a non-root uid
# inside its container. 0755 covers read/traverse (needed for
# root_ca.crt/pw below), but `step ca certificate` also *writes*
# fullchain.pem/privkey.pem into this same dir, which a non-owner can't
# do without write permission too — confirmed live ("permission denied"
# writing fullchain.pem with 0755). Throwaway scratch data for a single
# CI job step, so world-writable is a fine trade for not needing to
# guess/match the image's exact uid.
chmod 777 "$workdir"
cleanup() {
  rm -rf "$workdir"
  docker rm -f ci-step-ca >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker run -d --name ci-step-ca --network "$network" \
  -e "DOCKER_STEPCA_INIT_NAME=CI Throwaway CA" \
  -e "DOCKER_STEPCA_INIT_DNS_NAMES=ci-step-ca" \
  -e "DOCKER_STEPCA_INIT_PASSWORD=${ca_password}" \
  "$step_ca_image"

echo "Waiting for the throwaway step-ca to report healthy..."
status="unknown"
for _ in $(seq 1 30); do
  status=$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}' ci-step-ca)
  [ "$status" = "healthy" ] && break
  sleep 2
done
if [ "$status" != "healthy" ]; then
  echo "::error::ci-step-ca never became healthy"
  docker logs ci-step-ca
  exit 1
fi

# Fetched to a real file rather than passed via process substitution —
# `docker run --root <(...)` doesn't work across the container boundary,
# the fd only exists in the host shell that spawned it.
docker run --rm --network "$network" "$step_ca_image" \
  cat /home/step/certs/root_ca.crt > "$workdir/root_ca.crt"
chmod 644 "$workdir/root_ca.crt"

printf '%s' "$ca_password" > "$workdir/pw"
chmod 644 "$workdir/pw"

docker run --rm --network "$network" -v "$workdir:/work" "$step_cli_image" \
  step ca certificate lldap /work/fullchain.pem /work/privkey.pem \
    --san lldap --san "$lldap_fqdn" \
    --provisioner admin \
    --password-file /work/pw \
    --ca-url https://ci-step-ca:9000 \
    --root /work/root_ca.crt \
    --force

docker run --rm -v lldap_certs:/out -v "$workdir:/in:ro" alpine \
  cp /in/fullchain.pem /in/privkey.pem /out/
