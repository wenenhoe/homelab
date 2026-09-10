# r2-read-watcher's policy (ADR 0026, docs/openbao-vault-bootstrap.md).
# Applied by hand via vault-bootstrap, same convention as
# controller.hcl/vault-bootstrap.hcl's own header comments - not
# seeded via docker/openbao/configs/, not written by Ansible.
#
# Read-only on exactly the Telegram secrets check_freshness.py already
# reads (ADR 0021's hosts/all/telegram/* convention) - nothing else.
# This identity never touches cloud_credentials/{leaf,rotation}/* or
# any other hosts/* path; alerting on a detected R2-token read needs
# telegram-token/-chat-id/-topic-id-backups and nothing more.

path "secret/data/hosts/all/telegram/*" {
  capabilities = ["read"]
}
