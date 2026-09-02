"""Both CLI entry points' --help formatting should match.

Regression test for an inherited inconsistency: create_leaf_keys.py's
parser used RawDescriptionHelpFormatter (preserves its docstring's
paragraph breaks), create_rotation_keys.py's parser didn't (argparse's
default formatter re-wraps a multi-paragraph docstring into one dense
block, losing the blank-line breaks) - fixed to match rather than
carried forward.

Run via `uv run pytest ansible/tests/ -v`.
"""

from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from cloud_credentials import create_leaf_keys, create_rotation_keys


def _help_text(module, monkeypatch) -> str:
    monkeypatch.setattr(sys, "argv", ["prog", "--help"])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), pytest.raises(SystemExit):
        module.main()
    return buf.getvalue()


def test_create_leaf_keys_help_preserves_paragraph_breaks(monkeypatch):
    help_text = _help_text(create_leaf_keys, monkeypatch)
    # Two adjacent paragraphs from the real docstring - must stay
    # separated by a blank line, not collapsed by re-wrapping.
    assert "\nSafe to re-run" in help_text
    assert "\n\nSafe to re-run" in help_text, (
        "expected a blank line before this paragraph - RawDescriptionHelpFormatter "
        "regressed to argparse's default, which re-wraps the whole docstring as one blob"
    )


def test_create_rotation_keys_help_preserves_paragraph_breaks(monkeypatch):
    help_text = _help_text(create_rotation_keys, monkeypatch)
    # Same check on create_rotation_keys.py's own docstring - this is
    # the one that was actually missing RawDescriptionHelpFormatter.
    assert "\nR2 has no provider here at all" in help_text
    assert "\n\nR2 has no provider here at all" in help_text, (
        "expected a blank line before this paragraph - argparse's default formatter re-wraps the whole multi-paragraph docstring as one blob"
    )
