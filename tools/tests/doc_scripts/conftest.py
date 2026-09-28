"""Puts tools/ on sys.path so these tests import `doc_scripts` as the package it is.

Loaded by pytest before any test module here, so no test depends on another
file (or on import order) having set the path first.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
