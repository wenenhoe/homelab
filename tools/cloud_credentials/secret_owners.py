"""Every secret name cloud_credentials stores in Vault, paired with the module
whose has_secret/read_secret/write_secret owns it.

Shared by openbao_utils' dump, restore, audit and bootstrap, so none of them
keeps a second list that can drift from what cache.py's scoped() writes.
Pairing each name with its owning module, instead of rebuilding Vault paths by
hand here, also keeps every consumer on the category (leaf or rotation) that
module actually binds - see cache.py's scoped() docstring.

Names with a secret_catalog.yaml entry are listed too; the rest are
bookkeeping values written by rotation code, which only this list knows about.
"""

from __future__ import annotations

from cloud_credentials import create_snapshot_write_keys as snap
from cloud_credentials.leaf_keys import b2 as leaf_b2
from cloud_credentials.leaf_keys import oci as leaf_oci
from cloud_credentials.leaf_keys import r2 as leaf_r2
from cloud_credentials.rotation_keys import b2 as rotation_b2
from cloud_credentials.rotation_keys import oci_bootstrap as rotation_oci
from cloud_credentials.rotation_keys import r2 as rotation_r2

SECRET_OWNERS = [
    ("backblaze-b2-write-access-key", leaf_b2),
    ("backblaze-b2-write-secret-key", leaf_b2),
    ("backblaze-b2-read-access-key", leaf_b2),
    ("backblaze-b2-read-secret-key", leaf_b2),
    ("backblaze-b2-region", leaf_b2),
    ("_rotation-key-backblaze-b2-key-id", rotation_b2),
    ("_rotation-key-backblaze-b2-application-key", rotation_b2),
    ("oci-write-access-key", leaf_oci),
    ("oci-write-secret-key", leaf_oci),
    ("oci-write-scim-id", leaf_oci),
    ("oci-read-access-key", leaf_oci),
    ("oci-read-secret-key", leaf_oci),
    ("oci-read-scim-id", leaf_oci),
    ("oci-namespace", leaf_oci),
    ("oci-region", leaf_oci),
    ("_oci-leaf-user-ocid-write", rotation_oci),
    ("_oci-leaf-user-ocid-read", rotation_oci),
    ("_rotation-key-oci-domain-url", rotation_oci),
    ("_rotation-key-oci-client-id", rotation_oci),
    ("_rotation-key-oci-client-secret", rotation_oci),
    ("_rotation-key-oci-app-id", rotation_oci),
    ("_rotation-key-oci-created-at", rotation_oci),
    ("cloudflare-r2-account-id", leaf_r2),
    ("cloudflare-r2-write-access-key", leaf_r2),
    ("cloudflare-r2-write-secret-key", leaf_r2),
    ("cloudflare-r2-read-access-key", leaf_r2),
    ("cloudflare-r2-read-secret-key", leaf_r2),
    ("_rotation-key-cloudflare-r2-token", rotation_r2),
    (snap.VAULT_NAME_B2_ACCESS, snap),
    (snap.VAULT_NAME_B2_SECRET, snap),
    (snap.VAULT_NAME_R2_ACCESS, snap),
    (snap.VAULT_NAME_R2_SECRET, snap),
]
