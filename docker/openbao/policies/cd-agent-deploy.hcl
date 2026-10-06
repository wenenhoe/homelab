# cd-agent-deploy's policy (ADR 0020 revision 1,
# docs/topics/secrets/openbao-cd-agent-approles.md). Applied by hand via
# vault-bootstrap, same convention as controller.hcl's header comment.
#
# `create` without `update` on hosts/*: the secrets play writes a
# generated secret with cas=0, which OpenBao authorizes as `create` only
# while the path does not exist. A deploy job can add a new secret and
# can never overwrite an existing one. No rotation/* access at all.

path "secret/data/hosts/*" {
  capabilities = ["create", "read"]
}

path "secret/data/cloud_credentials/leaf/*" {
  capabilities = ["read"]
}
