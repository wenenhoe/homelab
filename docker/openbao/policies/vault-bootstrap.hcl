# vault-bootstrap's policy (ADR 0025, docs/openbao-vault-bootstrap.md).
# Applied by hand via that doc's runbook, same reasoning as
# controller.hcl's own header comment - not seeded via
# docker/openbao/configs/, and not written by Ansible.
#
# Deliberately narrow: enough to mint new policies/AppRoles when this
# repo needs a new Vault identity (a watcher, a future cd_agent role),
# nothing else. No secret/data/* access of any kind - this role cannot
# read a single application credential. No sys/generate-root-token/*
# either: that capability is added to a copy of this policy only for
# the duration of an actual root-recovery need, then removed again -
# see docs/openbao-vault-bootstrap.md's "Using this for emergency root
# access" section. Baking it in permanently would make this role a
# slower-to-notice root token instead of the narrower thing it's
# meant to be.

path "sys/policies/acl/*" {
  capabilities = ["create", "read", "update"]
}

path "auth/approle/role/*" {
  capabilities = ["create", "read", "update"]
}

path "auth/approle/role/+/role-id" {
  capabilities = ["read"]
}

path "auth/approle/role/+/secret-id" {
  capabilities = ["create", "update"]
}
