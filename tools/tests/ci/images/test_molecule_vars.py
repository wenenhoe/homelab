"""Tests for ci.images.molecule_vars: Molecule playbooks and the shared image files.

The check runs against a scratch tree with one drift at a time, so each error
is shown to fire; the last class checks the real repo.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from ci.images import molecule_vars as mv

VARS = "ansible/roles/molecule_helpers/vars/images"
SCENARIO = "ansible/roles/r/molecule/default"


def load(*names: str) -> str:
    entries = "".join(f'    - "{{{{ playbook_dir }}}}/../../../molecule_helpers/vars/images/{name}.yml"\n' for name in names)
    return f"  vars_files:\n{entries}"


def play(*loads: str, body: str = "") -> str:
    return f"- name: Verify\n  hosts: all\n{load(*loads) if loads else ''}  tasks:\n{body}"


USES_ALPINE = "    - ansible.builtin.command: docker run --rm -v v:/v {{ molecule_helpers_alpine_image }} true\n"
USES_AWS = '    - community.docker.docker_container:\n        image: "{{ molecule_helpers_aws_cli_image }}"\n'


class Tree:
    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def errors(self) -> list[str]:
        return mv.check(self.root)


@pytest.fixture
def tree(root):
    """Two image files and two plays that load exactly what they use."""
    tree = Tree(root)
    tree.write(f"{VARS}/alpine.yml", '---\nmolecule_helpers_alpine_image: "alpine:3.24"\n')
    tree.write(f"{VARS}/aws_cli.yml", '---\nmolecule_helpers_aws_cli_image: "amazon/aws-cli:2.15.0"\n')
    tree.write(f"{SCENARIO}/converge.yml", play("alpine", body=USES_ALPINE))
    tree.write(f"{SCENARIO}/verify.yml", play("aws_cli", body=USES_AWS))
    return tree


class TestAgreeingTree:
    def test_agreeing_tree_has_no_errors(self, tree):
        assert tree.errors() == []

    def test_a_tree_with_no_roles_has_only_the_missing_images_error(self, tree):
        (tree.root / "ansible/roles/r").rename(tree.root / "elsewhere")
        assert sorted(tree.errors()) == [f"{VARS}/alpine.yml: no play loads it", f"{VARS}/aws_cli.yml: no play loads it"]


class TestImageFile:
    def test_a_missing_directory_is_an_error(self, tree):
        for path in (tree.root / VARS).iterdir():
            path.unlink()
        (tree.root / VARS).rmdir()
        assert f"{VARS} doesn't exist" in tree.errors()

    def test_an_unquoted_value_is_an_error(self, tree):
        tree.write(f"{VARS}/alpine.yml", "molecule_helpers_alpine_image: alpine:3.24\n")
        (error, *_) = tree.errors()
        assert "alpine.yml: must hold exactly one" in error

    def test_a_second_line_is_an_error(self, tree):
        tree.write(f"{VARS}/alpine.yml", '---\nmolecule_helpers_alpine_image: "alpine:3.24"\nextra: 1\n')
        assert "must hold exactly one" in tree.errors()[0]

    def test_comments_and_the_document_marker_are_allowed(self, tree):
        tree.write(f"{VARS}/alpine.yml", '---\n# why\nmolecule_helpers_alpine_image: "alpine:3.24"\n')
        assert tree.errors() == []

    def test_a_variable_named_for_another_file_is_an_error(self, tree):
        tree.write(f"{VARS}/alpine.yml", '---\nmolecule_helpers_curl_image: "curlimages/curl:8.22.0"\n')
        assert "defines molecule_helpers_curl_image, but the file is named alpine" in tree.errors()[0]


class TestLiteral:
    def test_a_literal_in_a_command_is_an_error(self, tree):
        tree.write(f"{SCENARIO}/converge.yml", play("alpine", body=USES_ALPINE + "    - ansible.builtin.command: docker run --rm alpine:3.20 true\n"))
        (error,) = tree.errors()
        assert "converge.yml:7: names alpine:3.20 literally; use {{ molecule_helpers_alpine_image }} and load vars/images/alpine.yml" in error

    def test_a_literal_image_key_is_an_error(self, tree):
        tree.write(
            f"{SCENARIO}/verify.yml", play("aws_cli", body=USES_AWS + "    - community.docker.docker_container:\n        image: amazon/aws-cli:2.20.0\n")
        )
        (error,) = tree.errors()
        assert "names amazon/aws-cli:2.20.0 literally" in error

    def test_a_literal_in_a_task_file_is_an_error(self, tree):
        tree.write(f"{SCENARIO}/extra.yml", "- ansible.builtin.command: docker run alpine:3.24 true\n")
        assert any("extra.yml:1: names alpine:3.24 literally" in e for e in tree.errors())

    def test_a_commented_literal_is_ignored(self, tree):
        tree.write(f"{SCENARIO}/converge.yml", play("alpine", body="    # was alpine:3.20\n" + USES_ALPINE.rstrip() + "  # alpine:3.19\n"))
        assert tree.errors() == []

    def test_fixture_files_keep_their_own_pin(self, tree):
        tree.write(f"{SCENARIO}/files/docker/app/compose.yaml", "services:\n  a:\n    image: alpine:3.24\n")
        assert tree.errors() == []

    def test_a_symlinked_file_is_not_followed(self, tree):
        target = tree.root / "outside.yml"
        target.write_text("- ansible.builtin.command: docker run alpine:3.24 true\n")
        (tree.root / SCENARIO / "linked.yml").symlink_to(target)
        assert tree.errors() == []

    def test_a_longer_repo_name_is_not_a_match(self, tree):
        tree.write(f"{SCENARIO}/converge.yml", play("alpine", body=USES_ALPINE + "    - ansible.builtin.command: docker run myorg/alpine:3.24 true\n"))
        assert tree.errors() == []

    def test_the_variable_name_is_not_a_literal(self, tree):
        assert not any("literally" in e for e in tree.errors())


class TestLoad:
    def test_using_a_variable_without_loading_its_file_is_an_error(self, tree):
        tree.write(f"{SCENARIO}/converge.yml", play(body=USES_ALPINE))
        (error, orphan) = tree.errors()
        assert "converge.yml: uses molecule_helpers_alpine_image but doesn't load vars/images/alpine.yml" in error
        assert orphan == f"{VARS}/alpine.yml: no play loads it"

    def test_loading_a_file_nothing_uses_is_an_error(self, tree):
        tree.write(f"{SCENARIO}/converge.yml", play("alpine", "aws_cli", body=USES_ALPINE))
        (error,) = tree.errors()
        assert "loads vars/images/aws_cli.yml but nothing it runs uses molecule_helpers_aws_cli_image" in error

    def test_using_a_variable_no_file_defines_is_an_error(self, tree):
        tree.write(
            f"{SCENARIO}/converge.yml", play("alpine", body=USES_ALPINE + "    - ansible.builtin.command: docker run {{ molecule_helpers_nope_image }} true\n")
        )
        (error,) = tree.errors()
        assert "uses molecule_helpers_nope_image, which no file in" in error

    def test_a_load_path_that_misses_the_file_is_an_error(self, tree):
        tree.write(f"{SCENARIO}/converge.yml", play("alpine", body=USES_ALPINE).replace("../../../molecule_helpers", "../../molecule_helpers"))
        assert any("vars_files entry for alpine doesn't resolve" in e for e in tree.errors())

    def test_a_play_without_any_image_needs_no_load(self, tree):
        tree.write(f"{SCENARIO}/cleanup.yml", play(body="    - ansible.builtin.debug:\n        msg: hi\n"))
        assert tree.errors() == []

    def test_a_file_no_play_loads_is_an_error(self, tree):
        tree.write(f"{VARS}/curl.yml", '---\nmolecule_helpers_curl_image: "curlimages/curl:8.22.0"\n')
        assert tree.errors() == [f"{VARS}/curl.yml: no play loads it"]

    def test_a_single_quoted_load_is_read(self, tree):
        text = play("alpine", body=USES_ALPINE).replace('- "{{', "- '{{").replace('.yml"\n', ".yml'\n")
        tree.write(f"{SCENARIO}/converge.yml", text)
        assert tree.errors() == []


@pytest.fixture
def tree_with_task_file(tree):
    tree.write(f"{SCENARIO}/verify_extra.yml", "- ansible.builtin.command: docker run {{ molecule_helpers_alpine_image }} true\n")
    return tree


class TestImportedTaskFile:
    def test_a_task_file_counts_for_the_play_that_imports_it(self, tree_with_task_file):
        tree_with_task_file.write(f"{SCENARIO}/verify.yml", play("aws_cli", "alpine", body=USES_AWS + "    - ansible.builtin.import_tasks: verify_extra.yml\n"))
        assert tree_with_task_file.errors() == []

    def test_the_importing_play_must_load_what_the_task_file_uses(self, tree_with_task_file):
        tree_with_task_file.write(f"{SCENARIO}/verify.yml", play("aws_cli", body=USES_AWS + "    - ansible.builtin.include_tasks: verify_extra.yml\n"))
        (error,) = tree_with_task_file.errors()
        assert "verify.yml: uses molecule_helpers_alpine_image but doesn't load" in error

    def test_imports_are_followed_transitively(self, tree_with_task_file):
        tree_with_task_file.write(f"{SCENARIO}/verify_extra.yml", "- ansible.builtin.import_tasks: verify_deeper.yml\n")
        tree_with_task_file.write(f"{SCENARIO}/verify_deeper.yml", "- ansible.builtin.command: docker run {{ molecule_helpers_alpine_image }} true\n")
        tree_with_task_file.write(f"{SCENARIO}/verify.yml", play("aws_cli", "alpine", body=USES_AWS + "    - ansible.builtin.import_tasks: verify_extra.yml\n"))
        assert tree_with_task_file.errors() == []

    def test_a_task_file_no_play_runs_is_an_error(self, tree_with_task_file):
        assert tree_with_task_file.errors() == [f"{SCENARIO}/verify_extra.yml: uses molecule_helpers_*_image but no play in this scenario runs it"]


class TestRealRepo:
    def test_the_repo_has_no_drift(self):
        assert mv.check(mv.REPO_ROOT) == []

    def test_the_repo_pins_every_expected_image(self):
        pins, errors = mv._pins(mv.REPO_ROOT)
        assert errors == []
        assert sorted(pins) == ["alpine", "aws_cli", "curl", "lldap", "step_cli"]
