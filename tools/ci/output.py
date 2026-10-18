"""Writing step outputs the way GitHub Actions reads them."""

from __future__ import annotations

import os


def write_output(name: str, value: str) -> None:
    """Append `name=value` to $GITHUB_OUTPUT, or print it when run outside Actions.

    Values here are single-line (JSON arrays, booleans), which is all the
    plain `name=value` form can carry.
    """
    line = f"{name}={value}"
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as fh:
            fh.write(line + "\n")
    else:
        print(line)


def write_summary(title: str, lines: list[str]) -> None:
    """Append `lines` as a bulleted list under `### title` to the job summary, when running in Actions."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as fh:
            fh.write(f"### {title}\n\n" + "\n".join(f"- {line}" for line in lines) + "\n")
