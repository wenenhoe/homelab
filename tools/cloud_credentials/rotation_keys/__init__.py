"""One-time rotation-key bootstrap logic, one module per provider (plus
oci_iam.py's generic OCI IAM helpers, shared by both OCI bootstrap
functions in oci_bootstrap.py).

Used by create_rotation_keys.py, authenticating with your personal
admin identity - never read by the leaf_keys/ flow.
"""
