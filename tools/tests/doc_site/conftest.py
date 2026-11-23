"""A throwaway repository tree with the three views and a few documents, to build the site from."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "doc_scripts"))

import test_doc_coverage
from _doc_fixtures import project, revision
from doc_scripts.generate_doc_indexes import intro_path
from doc_site.site import VIEWS

INTRO = "A view with [a link](decision-index.md#by-number), `code` and **bold** text.\n\nA second paragraph."


@pytest.fixture
def tree(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = test_doc_coverage.tree(tmp_path_factory.mktemp("tree"))
    for view in VIEWS:
        path = root / intro_path(view.source)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {view.nav} view\n\n{INTRO}\n", encoding="utf-8")
    (root / "docs/projects").mkdir(parents=True, exist_ok=True)
    (root / "docs/projects/README.md").write_text("# Projects\n\n## Initiatives\n\n1. `base`\n", encoding="utf-8")
    (root / "docs/topics/infra").mkdir(parents=True, exist_ok=True)
    (root / "docs/topics/README.md").write_text("# Topics\n\n[the network](infra/network.md)\n", encoding="utf-8")
    (root / "docs/topics/infra/network.md").write_text("# The network\n\nBack to [the topics](../README.md).\n", encoding="utf-8")
    (root / "docs/README.md").write_text(
        "# Docs: where things go\n\n## Kinds\n\nSee [the topics](topics/README.md) and [the diagrams](architecture/README.md).\n", encoding="utf-8"
    )
    (root / "docs/architecture").mkdir(parents=True, exist_ok=True)
    (root / "docs/architecture/README.md").write_text("# Architecture\n\n[the flow](flow.md), or [home](../README.md)\n", encoding="utf-8")
    (root / "docs/architecture/flow.md").write_text("# A flow\n\n## Steps\n\nBack to [the index](README.md).\n", encoding="utf-8")
    revision(root, "0001-a", 0, status="approved")
    revision(root, "0002-b", 0, status="working")
    project(root, "one", status="building", decision="ADR-0001/0", super_project="base")
    project(root, "two", status="not-started", super_project="base")
    return root
