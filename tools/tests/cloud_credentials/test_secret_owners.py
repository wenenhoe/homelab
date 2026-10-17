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

import ast
import fnmatch
from pathlib import Path

import pytest
from cloud_credentials.leaf_keys import b2 as leaf_b2
from cloud_credentials.leaf_keys import oci as leaf_oci
from cloud_credentials.leaf_keys import r2 as leaf_r2
from cloud_credentials.secret_owners import SECRET_OWNERS
from utils.secret_catalog import CATALOG_PATH, load_catalog, openbao_scopes

_REQUIRED_ATTRS = ("has_secret", "read_secret", "write_secret")

_LEAF_MODULES = (leaf_b2, leaf_oci, leaf_r2)
_ROTATION_MODULE_PREFIX = "cloud_credentials.rotation_keys."


def _rotation_scoped_reads(module) -> list[str]:
    """Glob patterns for every secret name `module` passes to a function it
    bound from `scoped("rotation")` (e.g. leaf_keys/oci.py's
    `_rotation_require_secret`). An f-string name becomes a pattern, and a
    name held in a local constant is followed to its value. Any other
    argument fails loudly instead of being skipped."""
    tree = ast.parse(Path(module.__file__).read_text())
    bound: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and getattr(node.value.func, "id", None) == "scoped"
            and ast.literal_eval(node.value.args[0]) == "rotation"
        ):
            bound |= {target.id for target in node.targets[0].elts if target.id != "_"}

    patterns: list[str] = []
    for function in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        constants = {
            node.targets[0].id: node.value.value
            for node in ast.walk(function)
            if isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        }
        for call in (n for n in ast.walk(function) if isinstance(n, ast.Call) and getattr(n.func, "id", None) in bound):
            arg = call.args[0]
            if isinstance(arg, ast.Constant):
                patterns.append(arg.value)
            elif isinstance(arg, ast.JoinedStr):
                patterns.append("".join(part.value if isinstance(part, ast.Constant) else "*" for part in arg.values))
            elif isinstance(arg, ast.Name) and arg.id in constants:
                patterns.append(constants[arg.id])
            else:
                raise AssertionError(f"{module.__name__}:{call.lineno} passes a name this test can't resolve: {ast.unparse(arg)}")
    return patterns


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

    @pytest.mark.parametrize("leaf_module", _LEAF_MODULES, ids=lambda m: m.__name__)
    def test_names_a_leaf_module_reads_through_a_rotation_binding_are_paired_with_a_rotation_module(self, leaf_module):
        owners = dict(SECRET_OWNERS)
        patterns = _rotation_scoped_reads(leaf_module)
        assert patterns, f"{leaf_module.__name__} has no rotation-scoped read to check"

        problems: list[str] = []
        for pattern in patterns:
            matches = fnmatch.filter(owners, pattern)
            if not matches:
                problems.append(f"{pattern}: not listed in SECRET_OWNERS")
            problems += [f"{name}: paired with {owners[name].__name__}" for name in matches if not owners[name].__name__.startswith(_ROTATION_MODULE_PREFIX)]
        assert problems == [], f"names read through a rotation binding but not owned by a rotation module: {problems}"

    def test_a_name_with_a_catalog_entry_is_stored_at_the_entrys_scope(self, fake_vault, subtests):
        scopes = openbao_scopes(load_catalog(CATALOG_PATH))
        for name, module in SECRET_OWNERS:
            if name not in scopes:
                continue
            with subtests.test(name=name):
                module.write_secret(name, "value")
                assert fake_vault.get_path(f"{scopes[name]}/{name}") == "value"
