"""Reading a `sha256sum`-style manifest, and comparing a pin with its line."""

from __future__ import annotations

import re

_LINE = re.compile(r"^(?P<hash>[0-9a-fA-F]{64})[ \t]+\*?(?P<name>\S.*?)[ \t]*$")


def parse(text: str) -> dict[str, set[str]]:
    """File name -> every hash the manifest lists for it. A leading `./` on a name is dropped."""
    listed: dict[str, set[str]] = {}
    for line in text.splitlines():
        match = _LINE.match(line)
        if match:
            listed.setdefault(match.group("name").removeprefix("./"), set()).add(match.group("hash").lower())
    return listed


def mismatch(listed: dict[str, set[str]], file: str, pin: str) -> str | None:
    """Why `pin` isn't the manifest's hash for `file`, or None when it is.

    A name the manifest lists twice with different hashes is no answer to
    either, so it fails like a mismatch.
    """
    hashes = listed.get(file)
    if not hashes:
        return f"the manifest has no line for {file}"
    if hashes == {pin}:
        return None
    return f"the pin is {pin} but the manifest lists {', '.join(sorted(hashes))} for {file}"
