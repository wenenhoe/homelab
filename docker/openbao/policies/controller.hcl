# Controller's Era A AppRole policy (ADR 0022, docs/openbao-auth.md).
# Applied by hand via that doc's runbook, not by Ansible — writing it
# requires the initial root token, which docs/openbao.md's Init runbook
# already treats as something that must never touch a file or flow
# through Ansible's result-capture.
#
# Deliberately NOT under docker/openbao/configs/: that directory is
# app_registry.yaml's configs: source, seeded into the config named
# volume that OpenBao's own entrypoint auto-scans for server config at
# boot (see openbao.md's "Duplicate configuration" section) — a Vault
# ACL policy is not server config, and landing here would get it loaded
# (and fail to parse) as if it were. This file is never referenced by
# app_registry.yaml or copied by any Ansible task; it exists only for
# the runbook to scp by hand.

path "secret/data/hosts/*" {
  capabilities = ["create", "read", "update"]
}

path "secret/data/cloud_credentials/leaf/*" {
  capabilities = ["create", "read", "update"]
}

path "secret/data/cloud_credentials/rotation/*" {
  capabilities = ["create", "read", "update"]
}

# So snapshot-push.sh can eventually authenticate as this role instead
# of the operator exporting the root token by hand — see
# docs/openbao-backup-restore.md. Read-only: this role can pull a
# snapshot, never configure automated snapshots or anything else under
# sys/storage.
path "sys/storage/raft/snapshot" {
  capabilities = ["read"]
}
