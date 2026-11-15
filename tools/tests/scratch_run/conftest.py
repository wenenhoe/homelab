"""Fixtures of the scratch_run tests."""

from __future__ import annotations

import pytest
from scratch_run.spec import Spec, load_spec
from scratch_run_fakes import RUNS


@pytest.fixture
def rehearsal() -> Spec:
    return load_spec(RUNS / "rehearsal.yaml")
