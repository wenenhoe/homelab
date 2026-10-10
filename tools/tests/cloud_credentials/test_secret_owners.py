"""Interface smoke test for cloud_credentials.secret_owners.

Run via `uv run pytest tools/tests/ -v`. Every other test for
openbao_utils/restore.py/openbao_utils/audit.py exercises
their own logic against a fake module double (see those tests' own
comments for why) - which means neither one ever actually calls
has_secret()/read_secret()/write_secret() on the real leaf_keys/
rotation_keys modules SECRET_OWNERS pairs each name with. This test
exists specifically to close that gap: a module bound via
scoped()'s `_, _, _, _ = scoped(...)` pattern that discards one of the
three names those scripts need imports fine and passes every other test,
but breaks the first time openbao_utils/audit.py's has_secret() actually
dispatches to it.

No real Vault or file I/O here - purely checks that each paired module
exposes the three callables both scripts call, before either script
ever gets the chance to fail on a live controller.

It also pins that a name with a secret_catalog.yaml entry is stored at
that entry's scope, which openbao_utils/restore.py relies on to restore
it once, in its catalog phase, and not again through its owning module.
"""

from __future__ import annotations

from cloud_credentials.rotation_keys import b2 as rotation_b2
from cloud_credentials.rotation_keys import oci_bootstrap as rotation_oci
from cloud_credentials.rotation_keys import r2 as rotation_r2
from cloud_credentials.secret_owners import SECRET_OWNERS
from utils.secret_catalog import CATALOG_PATH, load_catalog, openbao_scopes

_REQUIRED_ATTRS = ("has_secret", "read_secret", "write_secret")

# Every secret name a leaf_keys module reads via its OWN second,
# rotation-scoped binding (e.g. leaf_keys/oci.py's
# _rotation_require_secret) - confirmed by hand against each
# module's actual source, not inferred. SECRET_OWNERS must pair
# every one of these with the rotation module, never the leaf module -
# e.g. _oci-leaf-user-ocid-{write,read} pair with rotation_oci, because
# leaf_keys/oci.py's own oci_leaf_user_id() reads it via
# _rotation_require_secret.
_CROSS_CATEGORY_ROTATION_NAMES = {
    "_rotation-key-backblaze-b2-key-id": rotation_b2,
    "_rotation-key-backblaze-b2-application-key": rotation_b2,
    "_oci-leaf-user-ocid-write": rotation_oci,
    "_oci-leaf-user-ocid-read": rotation_oci,
    "_rotation-key-cloudflare-r2-token": rotation_r2,
}


class TestSecretOwnersInterface:
    def test_every_paired_module_exposes_has_secret_read_secret_write_secret(self):
        missing: list[str] = []
        for name, module in SECRET_OWNERS:
            for attr in _REQUIRED_ATTRS:
                if not callable(getattr(module, attr, None)):
                    missing.append(f"{name} -> {module.__name__}.{attr}")
        assert missing == [], f"modules missing a required callable: {missing}"

    def test_names_are_unique(self):
        names = [name for name, _ in SECRET_OWNERS]
        assert len(names) == len(set(names)), "duplicate name in SECRET_OWNERS"

    def test_cross_category_names_are_paired_with_the_rotation_module_not_the_leaf_module(self):
        as_dict = dict(SECRET_OWNERS)
        wrong: list[str] = []
        for name, expected_module in _CROSS_CATEGORY_ROTATION_NAMES.items():
            actual_module = as_dict.get(name)
            if actual_module is not expected_module:
                wrong.append(f"{name}: paired with {getattr(actual_module, '__name__', actual_module)}, expected {expected_module.__name__}")
        assert wrong == [], f"cross-category names paired with the wrong module: {wrong}"

    def test_a_name_with_a_catalog_entry_is_stored_at_the_entrys_scope(self, fake_vault, subtests):
        scopes = openbao_scopes(load_catalog(CATALOG_PATH))
        for name, module in SECRET_OWNERS:
            if name not in scopes:
                continue
            with subtests.test(name=name):
                module.write_secret(name, "value")
                assert fake_vault.get_path(f"{scopes[name]}/{name}") == "value"
