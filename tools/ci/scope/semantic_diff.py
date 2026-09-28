"""Whether a changed file differs only in ways its consumer can't see.

detect-changes uses this to leave a file out of the Molecule scope when
its parsed content is identical before and after: a comment added,
edited or removed, or formatting changed (indentation, quoting, blank
lines). Comparing what the parser produces, not the text, is what makes
that safe: a `#` line inside a YAML block scalar is data and shows up as
a difference, where a line-based "starts with #" check would call it a
comment.

Only files whose parser is the consumer are eligible: YAML that Ansible
or Molecule itself loads (not YAML shipped as content, like a compose
fixture or a cloud-init file, where a leading `#cloud-config` comment
means something to the receiver), Python, and TOML. Anything else, any
file added, deleted or unparseable on either side, and any change that
leaves the bytes identical (a mode change), is a real change.

pyproject.toml is compared without `[tool.ruff]`, which only configures
a linter that pre-commit-checks runs over every file on every PR. Every
other table (the dependencies, the dependency groups, `[tool.uv]`, and
any tool table added later) still counts, so an unknown one errs toward
running the check.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

import yaml

from ci.scope.diff import read_at

# YAML that Ansible, ansible-galaxy or Molecule loads itself.
ELIGIBLE_YAML = tuple(
    re.compile(pattern)
    for pattern in (
        r"^ansible/roles/[^/]+/(tasks|handlers|defaults|vars|meta)/.+\.ya?ml$",
        r"^ansible/roles/[^/]+/molecule/[^/]+/[^/]+\.ya?ml$",
        r"^ansible/roles/[^/]+/molecule/[^/]+/(host_vars|group_vars)/.+\.ya?ml$",
        r"^ansible/roles/molecule_helpers/playbooks/.+\.ya?ml$",
        r"^ansible/roles/molecule_helpers/(role-)?requirements\.yml$",
        r"^ansible/requirements\.yml$",
        r"^ansible/(playbooks|inventory|ci-inventory)/.+\.ya?ml$",
        r"^\.config/molecule/.+\.ya?ml$",
    )
)
ELIGIBLE_TOML = ("pyproject.toml", "uv.lock")
# pyproject.toml tables no CI job other than pre-commit-checks reads.
LINT_ONLY_TOML_TABLES = (("tool", "ruff"),)

# UnicodeDecodeError is a ValueError.
_PARSE_ERRORS = (yaml.YAMLError, SyntaxError, ValueError)
_CODING = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*[-\w.]+")


def is_noop_change(path: str, old: bytes | None, new: bytes | None) -> bool:
    """True when `path`'s parsed content is identical in `old` and `new`."""
    if old is None or new is None or old == new:
        return False
    try:
        if any(pattern.match(path) for pattern in ELIGIBLE_YAML):
            return _yaml_data(old) == _yaml_data(new)
        if path.endswith(".py"):
            return _python_signature(old) == _python_signature(new)
        if path in ELIGIBLE_TOML:
            return _toml_data(path, old) == _toml_data(path, new)
    except _PARSE_ERRORS:
        return False
    return False


def _toml_data(path: str, raw: bytes) -> dict:
    data = tomllib.loads(raw.decode())
    if path == "pyproject.toml":
        for table in LINT_ONLY_TOML_TABLES:
            _drop_table(data, table)
    return data


def _drop_table(data: dict, table: tuple[str, ...]) -> None:
    """Remove a nested table, and any parent table that leaves empty."""
    parent = data
    for key in table[:-1]:
        if not isinstance(parent.get(key), dict):
            return
        parent = parent[key]
    parent.pop(table[-1], None)
    for depth in range(len(table) - 1, 0, -1):
        node = data
        for key in table[: depth - 1]:
            node = node[key]
        if node[table[depth - 1]] == {}:
            del node[table[depth - 1]]


def _yaml_data(raw: bytes) -> list:
    return list(yaml.safe_load_all(raw.decode()))


def _python_signature(raw: bytes) -> tuple:
    """The AST plus the two comment forms the interpreter itself reads."""
    text = raw.decode()
    lines = text.splitlines()
    shebang = lines[0] if lines and lines[0].startswith("#!") else None
    coding = tuple(line for line in lines[:2] if _CODING.match(line))
    return shebang, coding, ast.dump(ast.parse(text))


def is_noop_between(root: Path, base: str, head: str, path: str) -> bool:
    """is_noop_change for `path` as it stands at two git revisions."""
    return is_noop_change(path, read_at(root, base, path), read_at(root, head, path))
