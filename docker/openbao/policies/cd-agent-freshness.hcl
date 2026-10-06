# cd-agent-freshness's policy (ADR 0020 revision 1,
# docs/topics/secrets/openbao-cd-agent-approles.md). Applied by hand via
# vault-bootstrap, same convention as controller.hcl's header comment.
#
# Read-only on everything check_freshness.py reads: both
# cloud_credentials tiers (it asks each provider when a key expires) and
# the Telegram credentials it alerts with (ADR 0021). Reading the R2
# admin token's path is what makes r2-read-watcher name this role in the
# weekly alert (ADR 0026).

path "secret/data/cloud_credentials/leaf/*" {
  capabilities = ["read"]
}

path "secret/data/cloud_credentials/rotation/*" {
  capabilities = ["read"]
}

path "secret/data/hosts/all/telegram/*" {
  capabilities = ["read"]
}
