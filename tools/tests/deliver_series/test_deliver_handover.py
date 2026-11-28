"""What the session hands the maintainer."""

from __future__ import annotations

import re
from pathlib import Path

from deliver_series import handover
from deliver_series.build import Layer
from deliver_series.form import Commit, Identity
from deliver_series.plan import PlannedLayer

LANDING = Path(__file__).resolve().parents[3] / "docs" / "topics" / "engineering" / "landing-a-series.md"
WHO = Identity("Maint Ainer", "maint@example.invalid")


def commit(sha: str, subject: str) -> Commit:
    return Commit(sha, WHO, WHO, "2026-11-28 10:00:00 +0800", "2026-11-28 10:00:00 +0800", subject)


LAYERS = [
    Layer(1, PlannedLayer("tool-fix", 2, "fix(tool): mend it"), (commit("a" * 40, "fix(tool): one"), commit("b" * 40, "docs(tool): two"))),
    Layer(2, PlannedLayer("role-work", 1, None), (commit("c" * 40, "feat(caddy): change the role"),)),
]
PATHS = {
    "a" * 40: ["tools/tool/code.py", "tools/tests/tool/test_code.py"],
    "b" * 40: ["docs/topics/tool.md"],
    "c" * 40: ["ansible/roles/caddy/tasks/main.yaml", ".github/workflows/ci.yaml", "ansible/roles/bind9/tasks/main.yaml"],
}


def test_the_stop_list_names_each_commit_with_its_files() -> None:
    assert handover.stop_list(LAYERS, PATHS) == [
        ("0001a", "tool-fix", ["tools/tests/tool/test_code.py", "tools/tool/code.py"]),
        ("0002a", "role-work", [".github/workflows/ci.yaml"]),
    ]


def test_a_layer_that_touches_tooling_is_named_with_those_files_only() -> None:
    assert handover.tooling_layers(LAYERS, PATHS) == {
        "0001 tool-fix": ["tools/tests/tool/test_code.py", "tools/tool/code.py"],
        "0002 role-work": [".github/workflows/ci.yaml"],
    }


def test_each_changed_role_is_listed_as_not_verified() -> None:
    assert handover.unverified_roles(LAYERS, PATHS) == ["bind9", "caddy"]


def test_the_handover_names_the_layers_what_was_skipped_and_what_was_not_run() -> None:
    text = handover.render(Path("/out/0001-0002.series"), LAYERS, PATHS, {"zizmor": "the GitHub API: answered 403"})

    assert text == "\n".join(
        [
            "Series file: /out/0001-0002.series",
            "",
            "Layers:",
            "- 0001 tool-fix: fix(tool): mend it (2 commits)",
            "- 0002 role-work: feat(caddy): change the role (1 commit)",
            "",
            "On the stop list (read each patch before accepting it):",
            "- 0001a tool-fix: tools/tests/tool/test_code.py, tools/tool/code.py",
            "- 0002a role-work: .github/workflows/ci.yaml",
            "",
            "Touching a hook, CI or tooling path:",
            "- 0001 tool-fix: tools/tests/tool/test_code.py, tools/tool/code.py",
            "- 0002 role-work: .github/workflows/ci.yaml",
            "",
            "Not checked:",
            "- hook `zizmor` skipped: the GitHub API: answered 403",
            "- Molecule for the role `bind9` was not run",
            "- Molecule for the role `caddy` was not run",
        ]
    )


def test_a_series_with_nothing_skipped_says_so() -> None:
    plain = [Layer(1, PlannedLayer("docs-only", 1, None), (commit("d" * 40, "docs(x): y"),))]

    text = handover.render(Path("/out/0001-0001.series"), plain, {"d" * 40: ["docs/x.md"]}, {})

    assert text.endswith("Not checked:\n- nothing skipped; no Molecule scenario is run by a delivery")


def normalised(block: str) -> str:
    """A block without its trailing comments, which the topic doc adds to say what each command does."""
    return "\n".join(re.sub(r"\s+#.*$", "", line) if not line.startswith("#") else line for line in block.strip().splitlines())


def test_the_commands_are_the_ones_landing_a_series_gives() -> None:
    blocks = re.findall(r"```bash\n(.*?)```", LANDING.read_text(), flags=re.DOTALL)[:3]

    assert [normalised(block) for block in blocks] == [normalised(block) for block in re.findall(r"```bash\n(.*?)```", handover.commands(), flags=re.DOTALL)]
