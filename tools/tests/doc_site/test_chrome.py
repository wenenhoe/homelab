"""How Chrome is started: sandboxed, except as root, where it cannot be."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import create_autospec

import pytest

pytest.importorskip("playwright")

from doc_site import chrome
from playwright.sync_api import BrowserType


@pytest.mark.parametrize(("euid", "sandboxed"), [pytest.param(1000, True, id="user"), pytest.param(0, False, id="root")])
def test_chrome_is_sandboxed_unless_run_as_root(monkeypatch, euid, sandboxed):
    monkeypatch.setattr(os, "geteuid", create_autospec(os.geteuid, return_value=euid))
    chromium = create_autospec(BrowserType, instance=True)
    assert chrome.launch(SimpleNamespace(chromium=chromium)) is chromium.launch.return_value
    chromium.launch.assert_called_once_with(channel="chrome", chromium_sandbox=sandboxed)
