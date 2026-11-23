"""Unit tests for doc_stage_words.py: a doc or a comment that links a project
does not name that project's stage. Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import pytest
from doc_scripts import doc_stage_words as stage_words


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestNamingAStage:
    @pytest.mark.parametrize(
        "text",
        [
            "They wait for Stage 1 of [the network](../../projects/coding-agent-network.md).\n",
            "[The network](../../projects/coding-agent-network.md) reaches its stage 2 first.\n",
            "See [`gatehouse.md`](../projects/gatehouse.md), Phase B.\n",
            "Track A of PROJ-gatehouse adds it.\n",
            "Stages 3 and 4 of [it](projects/cd-agent.md) do the rest.\n",
        ],
    )
    def test_a_stage_word_beside_a_project_is_refused(self, root, text):
        write(root, "docs/topics/infra/a.md", text)
        [error] = stage_words.stage_word_errors(root)
        assert error.startswith("docs/topics/infra/a.md:1: ")

    def test_a_code_comment_is_judged_the_same_way(self, root):
        write(root, "ansible/roles/x/tasks/main.yaml", "# Stage 2 of docs/projects/cd-agent.md moves this.\n- name: x\n")
        [error] = stage_words.stage_word_errors(root)
        assert error.startswith("ansible/roles/x/tasks/main.yaml:1: ")

    def test_the_error_names_the_line_of_the_unit(self, root):
        write(root, "docs/topics/a.md", "# Title\n\nOne.\n\nStage 1 of [p](../projects/p.md)\ncontinues here.\n")
        [error] = stage_words.stage_word_errors(root)
        assert ":5: " in error


class TestNotNamingOne:
    def test_a_stage_word_with_no_project_is_a_playbook_s_own_step(self, root):
        write(root, "docs/topics/a.md", "Stage 1 starts OpenBao on loopback. Phase 2 restores the world.\n")
        write(root, "ansible/playbooks/p.yaml", "# Stage 3: OpenBao on a cert from the restored CA.\n")
        assert stage_words.stage_word_errors(root) == []

    def test_a_project_with_no_stage_word_is_fine(self, root):
        write(root, "docs/topics/a.md", "Owned by [the network](../projects/coding-agent-network.md), which adds the zone.\n")
        assert stage_words.stage_word_errors(root) == []

    def test_an_ordinary_use_of_the_word_is_not_a_stage(self, root):
        write(root, "docs/topics/a.md", "[p](../projects/p.md) lets a change stage a file, and a stage of a pipeline run, on a track.\n")
        assert stage_words.stage_word_errors(root) == []

    def test_the_stage_and_the_project_in_different_units_are_not_joined(self, root):
        write(
            root,
            "docs/topics/a.md",
            "- Owned by [p](../projects/p.md).\n- Stage 1 starts OpenBao.\n\n"
            "| Doc | Covers |\n| :--- | :--- |\n| [p](../projects/p.md) | The project |\n| `restore.md` | Stage 2 of a restore |\n\n"
            "Owned by [p](../projects/p.md).\n\nStage 3 of the restore.\n",
        )
        assert stage_words.stage_word_errors(root) == []

    @pytest.mark.parametrize("rel", ["docs/projects/p.md", "docs/decisions/0001-x/revision-000.md", "docs/explorations/q.md", "tools/tests/t.py"])
    def test_the_places_that_own_the_vocabulary_are_skipped(self, root, rel):
        write(root, rel, "Stage 1 of [p](../projects/p.md).\n")
        assert stage_words.stage_word_errors(root) == []

    def test_a_generated_view_is_skipped(self, root):
        write(root, "docs/project-planning.md", "Stage 1 of [p](projects/p.md).\n")
        assert stage_words.stage_word_errors(root) == []
