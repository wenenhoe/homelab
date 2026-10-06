# cd-agent-snapshot's policy (ADR 0020 revision 1,
# docs/topics/secrets/openbao-cd-agent-approles.md). Applied by hand via
# vault-bootstrap, same convention as controller.hcl's header comment.
#
# The six leaf paths are the ones snapshot-push.sh reads. Each is named
# rather than granted as leaf/*: this is the one job that downloads the
# whole raft database, so it must not also be able to read every other
# leaf credential.

path "sys/storage/raft/snapshot" {
  capabilities = ["read"]
}

path "secret/data/cloud_credentials/leaf/cloudflare-r2-openbao-snapshot-write-access-key" {
  capabilities = ["read"]
}

path "secret/data/cloud_credentials/leaf/cloudflare-r2-openbao-snapshot-write-secret-key" {
  capabilities = ["read"]
}

path "secret/data/cloud_credentials/leaf/backblaze-b2-openbao-snapshot-write-access-key" {
  capabilities = ["read"]
}

path "secret/data/cloud_credentials/leaf/backblaze-b2-openbao-snapshot-write-secret-key" {
  capabilities = ["read"]
}

path "secret/data/cloud_credentials/leaf/cloudflare-r2-account-id" {
  capabilities = ["read"]
}

path "secret/data/cloud_credentials/leaf/backblaze-b2-region" {
  capabilities = ["read"]
}
