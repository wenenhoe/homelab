"""The generated doc views, read from the list the apply hooks read.

`.githooks/generated-views` names them, one path per line. `pre-applypatch` stages
and regenerates them, `post-applypatch` amends them into the commit, and the hook
tests build their sandbox from it, so a view the list leaves out stops a `git am`
on a stale view. Code that must skip or recognise the views reads the list through
here instead of keeping its own.
"""

from __future__ import annotations

from pathlib import Path

from doc_scripts.doc_frontmatter import ROOT

LIST_RELATIVE = ".githooks/generated-views"


def generated_views(root: Path = ROOT) -> tuple[str, ...]:
    return tuple(line for line in (root / LIST_RELATIVE).read_text(encoding="utf-8").splitlines() if line.strip())
