"""A YAML loader that refuses a repeated mapping key.

`yaml.safe_load` keeps the last of two equal keys, so a repeated name in a
catalog would silently replace the first entry. Standard library and PyYAML
only, so a pre-commit hook can import it.
"""

from __future__ import annotations

import yaml


class UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that raises `ConstructorError` on a repeated string key in any mapping."""

    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if isinstance(key, str) and key in seen:
                raise yaml.constructor.ConstructorError(None, None, f"found duplicate key {key!r}", key_node.start_mark)
            seen.add(key)
        return super().construct_mapping(node, deep)
