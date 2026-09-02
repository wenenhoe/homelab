"""Cloud-credential tooling for cloud_sync's R2/B2/OCI backends.

Credential hierarchy (see docs/cloud-credential-creation.md):
  master key -> rotation key -> leaf key

- rotation_keys/ + create_rotation_keys.py: one-time bootstrap, run by
  hand with your personal admin identity.
- leaf_keys/ + create_leaf_keys.py: routine create/rotate of the actual
  write/read credentials cloud_sync and restore_discovery use, run with
  the cached rotation key.
- cache.py / verify.py: shared plumbing used by both.
"""
