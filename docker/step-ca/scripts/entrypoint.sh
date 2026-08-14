#!/bin/sh
# Entrypoint for the `step-ca` service in docker/step-ca/compose.yaml.
#
# The upstream image's own DOCKER_STEPCA_INIT_* auto-init encrypts both
# the CA keys and the initial JWK provisioner key with a single shared
# password, and has no flag for a non-default provisioner claim duration
# - see docs/step-ca.md. This runs the same `step ca init` operation by
# hand instead, to get both. It's still gated on the same idempotency
# check the stock entrypoint uses (config/ca.json not yet existing), so
# it's a one-time bootstrap of the identity persisted in the `data`
# volume, not a rebuild-time regeneration.
set -eu

CONFIG="${STEPPATH}/config/ca.json"
CA_PASSWORD_FILE=/tmp/step-ca-password
PROVISIONER_PASSWORD_FILE=/tmp/step-ca-provisioner-password

umask 077
printf '%s' "${STEP_CA_PASSWORD}" > "${CA_PASSWORD_FILE}"
printf '%s' "${STEP_CA_PROVISIONER_PASSWORD}" > "${PROVISIONER_PASSWORD_FILE}"

if [ ! -f "${CONFIG}" ]; then
    step ca init \
        --name "${STEP_CA_NAME}" \
        --dns "${STEP_CA_DNS_NAMES}" \
        --address ":9000" \
        --provisioner "${STEP_CA_PROVISIONER_NAME}" \
        --password-file "${CA_PASSWORD_FILE}" \
        --provisioner-password-file "${PROVISIONER_PASSWORD_FILE}" \
        --deployment-type standalone

    step ca provisioner update "${STEP_CA_PROVISIONER_NAME}" \
        --ca-config "${CONFIG}" \
        --x509-default-dur "${STEP_CA_DEFAULT_CERT_DURATION}"
fi

exec step-ca "${CONFIG}" --password-file "${CA_PASSWORD_FILE}"
