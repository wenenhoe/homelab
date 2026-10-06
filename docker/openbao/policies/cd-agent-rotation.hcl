# cd-agent-rotation's policy (ADR 0020 revision 1,
# docs/topics/secrets/openbao-cd-agent-approles.md). Applied by hand via
# vault-bootstrap, same convention as controller.hcl's header comment.
#
# Both cloud_credentials tiers and nothing under hosts/*: the rotation
# job has no business touching application secrets.

path "secret/data/cloud_credentials/leaf/*" {
  capabilities = ["create", "read", "update"]
}

path "secret/data/cloud_credentials/rotation/*" {
  capabilities = ["create", "read", "update"]
}
