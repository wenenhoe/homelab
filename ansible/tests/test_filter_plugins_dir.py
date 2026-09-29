"""Invariants of the repo-level filter plugin directory.

ansible.cfg names the directory, and .config/molecule/config.yml points
every Molecule scenario at that ansible.cfg, so this is the one place
filters live for playbooks, roles and scenarios alike.
"""

from __future__ import annotations

import configparser
import importlib.util
from pathlib import Path

ANSIBLE_DIR = Path(__file__).resolve().parent.parent
PLUGIN_DIR = ANSIBLE_DIR / "filter_plugins"


def _plugin_modules():
    for path in sorted(PLUGIN_DIR.glob("*.py")):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield path, module


def test_ansible_cfg_names_the_plugin_directory():
    cfg = configparser.ConfigParser()
    cfg.read(ANSIBLE_DIR / "ansible.cfg")
    assert (ANSIBLE_DIR / cfg["defaults"]["filter_plugins"]).resolve() == PLUGIN_DIR.resolve()


def test_directory_holds_at_least_one_plugin():
    assert list(PLUGIN_DIR.glob("*.py"))


def test_every_module_exposes_callable_filters():
    for path, module in _plugin_modules():
        filters = module.FilterModule().filters()
        assert filters, path.name
        assert all(callable(fn) for fn in filters.values()), path.name


def test_filter_names_are_unique_across_the_directory():
    names = [name for _, module in _plugin_modules() for name in module.FilterModule().filters()]
    assert len(names) == len(set(names))
