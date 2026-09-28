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
"""

from __future__ import annotations

import ast
import re
import tomllib

import yaml

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
            return tomllib.loads(old.decode()) == tomllib.loads(new.decode())
    except _PARSE_ERRORS:
        return False
    return False


def _yaml_data(raw: bytes) -> list:
    return list(yaml.safe_load_all(raw.decode()))


def _python_signature(raw: bytes) -> tuple:
    """The AST plus the two comment forms the interpreter itself reads."""
    text = raw.decode()
    lines = text.splitlines()
    shebang = lines[0] if lines and lines[0].startswith("#!") else None
    coding = tuple(line for line in lines[:2] if _CODING.match(line))
    return shebang, coding, ast.dump(ast.parse(text))
