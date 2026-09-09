"""Interface smoke test for cloud_credentials._legacy_cache_keys.

Run via `uv run pytest ansible/tests/ -v`. Every other test for
restore_cloud_credentials_from_backup.py/audit_secrets.py exercises
their own logic against a fake module double (see those tests' own
comments for why) - which means neither one ever actually calls
cached()/read_cache()/write_cache() on the real leaf_keys/
rotation_keys modules LEGACY_CACHE_KEYS pairs each key with. This test
exists specifically to close that gap: a module bound via
scoped()'s `_, _, _, _ = scoped(...)` pattern that discards one of the
three names those scripts need (as rotation_keys/r2.py's `read_cache`
once did) imports fine and passes every other test, but breaks the
first time audit_secrets.py's cached() actually dispatches to it.

No real Vault or file I/O here - purely checks that each paired module
exposes the three callables both scripts call, before either script
ever gets the chance to fail on a live controller.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from cloud_credentials._legacy_cache_keys import LEGACY_CACHE_KEYS
from cloud_credentials.rotation_keys import b2 as rotation_b2
from cloud_credentials.rotation_keys import oci_bootstrap as rotation_oci
from cloud_credentials.rotation_keys import r2 as rotation_r2

_REQUIRED_ATTRS = ("cached", "read_cache", "write_cache")

# Every key name a leaf_keys module reads via its OWN second,
# rotation-scoped binding (e.g. leaf_keys/oci.py's
# _rotation_require_cache_file) - confirmed by hand against each
# module's actual source, not inferred. LEGACY_CACHE_KEYS must pair
# every one of these with the rotation module, never the leaf module -
# exactly the class of bug that shipped in patch 0003 for
# _oci-leaf-user-ocid-{write,read} (paired with leaf_oci there,
# confirmed live against a real controller to be wrong: leaf_keys/
# oci.py's own oci_leaf_user_id() reads it via _rotation_require_cache_file).
_CROSS_CATEGORY_ROTATION_KEYS = {
    "_rotation-key-backblaze-b2-key-id": rotation_b2,
    "_rotation-key-backblaze-b2-application-key": rotation_b2,
    "_oci-leaf-user-ocid-write": rotation_oci,
    "_oci-leaf-user-ocid-read": rotation_oci,
    "_rotation-key-cloudflare-r2-token": rotation_r2,
}


class LegacyCacheKeysInterfaceTests(unittest.TestCase):
    def test_every_paired_module_exposes_cached_read_cache_write_cache(self):
        missing: list[str] = []
        for name, module in LEGACY_CACHE_KEYS:
            for attr in _REQUIRED_ATTRS:
                if not callable(getattr(module, attr, None)):
                    missing.append(f"{name} -> {module.__name__}.{attr}")
        self.assertEqual(missing, [], f"modules missing a required callable: {missing}")

    def test_key_names_are_unique(self):
        names = [name for name, _ in LEGACY_CACHE_KEYS]
        self.assertEqual(len(names), len(set(names)), "duplicate key name in LEGACY_CACHE_KEYS")

    def test_cross_category_keys_are_paired_with_the_rotation_module_not_the_leaf_module(self):
        as_dict = dict(LEGACY_CACHE_KEYS)
        wrong: list[str] = []
        for name, expected_module in _CROSS_CATEGORY_ROTATION_KEYS.items():
            actual_module = as_dict.get(name)
            if actual_module is not expected_module:
                wrong.append(f"{name}: paired with {getattr(actual_module, '__name__', actual_module)}, expected {expected_module.__name__}")
        self.assertEqual(wrong, [], f"cross-category keys paired with the wrong module: {wrong}")


if __name__ == "__main__":
    unittest.main()
