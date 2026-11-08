# Holds no secret: the endpoint, the key pair and the encryption key come from the
# environment (docs/topics/infra/tofu/state-and-credentials.md).
terraform {
  backend "s3" {
    bucket         = "opentofu-state"
    key            = "terraform.tfstate"
    region         = "auto"
    use_lockfile   = true
    use_path_style = true

    skip_credentials_validation = true
    skip_metadata_api_check     = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_s3_checksum            = true
  }
}
