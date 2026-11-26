"""The installed Google Chrome, as the build and the layout check start it."""

from __future__ import annotations

import os

from playwright.sync_api import Browser, Playwright


def launch(playwright: Playwright) -> Browser:
    """Headless Chrome with its sandbox on."""
    # Playwright passes `--no-sandbox` unless asked not to. Chrome does not start sandboxed as root, which a hosted sandbox may be.
    return playwright.chromium.launch(channel="chrome", chromium_sandbox=os.geteuid() != 0)
