"""Every cache key name cloud_credentials has ever written to Vault,
paired with the module whose write_cache/cached/read_cache owns it.
Shared by restore_cloud_credentials_from_backup.py, audit_secrets.py,
and bootstrap_secrets.py's own exclusion list, so none of them can
drift against each other or against what cache.py's scoped() actually
writes - duplicating this list per-consumer is what let
secrets_registry.yaml's header comment and bootstrap_secrets.py's own
behavior disagree, pre-Track-A-stage-6.

Reusing each module's own bound functions (rather than reconstructing
Vault paths by hand here) means this list can't drift from what the
real code actually classifies each key as either - see cache.py's
scoped() docstring.
"""

from __future__ import annotations

from cloud_credentials import create_snapshot_write_keys as snap
from cloud_credentials.leaf_keys import b2 as leaf_b2
from cloud_credentials.leaf_keys import oci as leaf_oci
from cloud_credentials.leaf_keys import r2 as leaf_r2
from cloud_credentials.rotation_keys import b2 as rotation_b2
from cloud_credentials.rotation_keys import oci_bootstrap as rotation_oci
from cloud_credentials.rotation_keys import r2 as rotation_r2

LEGACY_CACHE_KEYS = [
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
    (snap.CACHE_B2_ACCESS, snap),
    (snap.CACHE_B2_SECRET, snap),
    (snap.CACHE_R2_ACCESS, snap),
    (snap.CACHE_R2_SECRET, snap),
]
