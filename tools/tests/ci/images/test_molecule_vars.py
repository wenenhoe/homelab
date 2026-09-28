"""Tests for ci.images.molecule_vars: Molecule playbooks and the shared image files.

The check runs against a scratch tree with one drift at a time, so each error
is shown to fire; the last class checks the real repo.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

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


class ScratchTree(unittest.TestCase):
    """Two image files and two plays that load exactly what they use."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.write(f"{VARS}/alpine.yml", '---\nmolecule_helpers_alpine_image: "alpine:3.24"\n')
        self.write(f"{VARS}/aws_cli.yml", '---\nmolecule_helpers_aws_cli_image: "amazon/aws-cli:2.15.0"\n')
        self.write(f"{SCENARIO}/converge.yml", play("alpine", body=USES_ALPINE))
        self.write(f"{SCENARIO}/verify.yml", play("aws_cli", body=USES_AWS))

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def errors(self) -> list[str]:
        return mv.check(self.root)


class AgreeingTreeTests(ScratchTree):
    def test_agreeing_tree_has_no_errors(self):
        self.assertEqual(self.errors(), [])

    def test_a_tree_with_no_roles_has_only_the_missing_images_error(self):
        (self.root / "ansible/roles/r").rename(self.root / "elsewhere")
        self.assertEqual(sorted(self.errors()), [f"{VARS}/alpine.yml: no play loads it", f"{VARS}/aws_cli.yml: no play loads it"])


class ImageFileTests(ScratchTree):
    def test_a_missing_directory_is_an_error(self):
        for path in (self.root / VARS).iterdir():
            path.unlink()
        (self.root / VARS).rmdir()
        self.assertIn(f"{VARS} doesn't exist", self.errors())

    def test_an_unquoted_value_is_an_error(self):
        self.write(f"{VARS}/alpine.yml", "molecule_helpers_alpine_image: alpine:3.24\n")
        (error, *_) = self.errors()
        self.assertIn("alpine.yml: must hold exactly one", error)

    def test_a_second_line_is_an_error(self):
        self.write(f"{VARS}/alpine.yml", '---\nmolecule_helpers_alpine_image: "alpine:3.24"\nextra: 1\n')
        self.assertIn("must hold exactly one", self.errors()[0])

    def test_comments_and_the_document_marker_are_allowed(self):
        self.write(f"{VARS}/alpine.yml", '---\n# why\nmolecule_helpers_alpine_image: "alpine:3.24"\n')
        self.assertEqual(self.errors(), [])

    def test_a_variable_named_for_another_file_is_an_error(self):
        self.write(f"{VARS}/alpine.yml", '---\nmolecule_helpers_curl_image: "curlimages/curl:8.22.0"\n')
        self.assertIn("defines molecule_helpers_curl_image, but the file is named alpine", self.errors()[0])


class LiteralTests(ScratchTree):
    def test_a_literal_in_a_command_is_an_error(self):
        self.write(f"{SCENARIO}/converge.yml", play("alpine", body=USES_ALPINE + "    - ansible.builtin.command: docker run --rm alpine:3.20 true\n"))
        (error,) = self.errors()
        self.assertIn("converge.yml:7: names alpine:3.20 literally; use {{ molecule_helpers_alpine_image }} and load vars/images/alpine.yml", error)

    def test_a_literal_image_key_is_an_error(self):
        self.write(
            f"{SCENARIO}/verify.yml", play("aws_cli", body=USES_AWS + "    - community.docker.docker_container:\n        image: amazon/aws-cli:2.20.0\n")
        )
        (error,) = self.errors()
        self.assertIn("names amazon/aws-cli:2.20.0 literally", error)

    def test_a_literal_in_a_task_file_is_an_error(self):
        self.write(f"{SCENARIO}/extra.yml", "- ansible.builtin.command: docker run alpine:3.24 true\n")
        self.assertTrue(any("extra.yml:1: names alpine:3.24 literally" in e for e in self.errors()))

    def test_a_commented_literal_is_ignored(self):
        self.write(f"{SCENARIO}/converge.yml", play("alpine", body="    # was alpine:3.20\n" + USES_ALPINE.rstrip() + "  # alpine:3.19\n"))
        self.assertEqual(self.errors(), [])

    def test_fixture_files_keep_their_own_pin(self):
        self.write(f"{SCENARIO}/files/docker/app/compose.yaml", "services:\n  a:\n    image: alpine:3.24\n")
        self.assertEqual(self.errors(), [])

    def test_a_symlinked_file_is_not_followed(self):
        target = self.root / "outside.yml"
        target.write_text("- ansible.builtin.command: docker run alpine:3.24 true\n")
        (self.root / SCENARIO / "linked.yml").symlink_to(target)
        self.assertEqual(self.errors(), [])

    def test_a_longer_repo_name_is_not_a_match(self):
        self.write(f"{SCENARIO}/converge.yml", play("alpine", body=USES_ALPINE + "    - ansible.builtin.command: docker run myorg/alpine:3.24 true\n"))
        self.assertEqual(self.errors(), [])

    def test_the_variable_name_is_not_a_literal(self):
        self.assertFalse(any("literally" in e for e in self.errors()))


class LoadTests(ScratchTree):
    def test_using_a_variable_without_loading_its_file_is_an_error(self):
        self.write(f"{SCENARIO}/converge.yml", play(body=USES_ALPINE))
        (error, orphan) = self.errors()
        self.assertIn("converge.yml: uses molecule_helpers_alpine_image but doesn't load vars/images/alpine.yml", error)
        self.assertEqual(orphan, f"{VARS}/alpine.yml: no play loads it")

    def test_loading_a_file_nothing_uses_is_an_error(self):
        self.write(f"{SCENARIO}/converge.yml", play("alpine", "aws_cli", body=USES_ALPINE))
        (error,) = self.errors()
        self.assertIn("loads vars/images/aws_cli.yml but nothing it runs uses molecule_helpers_aws_cli_image", error)

    def test_using_a_variable_no_file_defines_is_an_error(self):
        self.write(
            f"{SCENARIO}/converge.yml", play("alpine", body=USES_ALPINE + "    - ansible.builtin.command: docker run {{ molecule_helpers_nope_image }} true\n")
        )
        (error,) = self.errors()
        self.assertIn("uses molecule_helpers_nope_image, which no file in", error)

    def test_a_load_path_that_misses_the_file_is_an_error(self):
        self.write(f"{SCENARIO}/converge.yml", play("alpine", body=USES_ALPINE).replace("../../../molecule_helpers", "../../molecule_helpers"))
        self.assertTrue(any("vars_files entry for alpine doesn't resolve" in e for e in self.errors()))

    def test_a_play_without_any_image_needs_no_load(self):
        self.write(f"{SCENARIO}/cleanup.yml", play(body="    - ansible.builtin.debug:\n        msg: hi\n"))
        self.assertEqual(self.errors(), [])

    def test_a_file_no_play_loads_is_an_error(self):
        self.write(f"{VARS}/curl.yml", '---\nmolecule_helpers_curl_image: "curlimages/curl:8.22.0"\n')
        self.assertEqual(self.errors(), [f"{VARS}/curl.yml: no play loads it"])

    def test_a_single_quoted_load_is_read(self):
        text = play("alpine", body=USES_ALPINE).replace('- "{{', "- '{{").replace('.yml"\n', ".yml'\n")
        self.write(f"{SCENARIO}/converge.yml", text)
        self.assertEqual(self.errors(), [])


class ImportedTaskFileTests(ScratchTree):
    def setUp(self):
        super().setUp()
        self.write(f"{SCENARIO}/verify_extra.yml", "- ansible.builtin.command: docker run {{ molecule_helpers_alpine_image }} true\n")

    def test_a_task_file_counts_for_the_play_that_imports_it(self):
        self.write(f"{SCENARIO}/verify.yml", play("aws_cli", "alpine", body=USES_AWS + "    - ansible.builtin.import_tasks: verify_extra.yml\n"))
        self.assertEqual(self.errors(), [])

    def test_the_importing_play_must_load_what_the_task_file_uses(self):
        self.write(f"{SCENARIO}/verify.yml", play("aws_cli", body=USES_AWS + "    - ansible.builtin.include_tasks: verify_extra.yml\n"))
        (error,) = self.errors()
        self.assertIn("verify.yml: uses molecule_helpers_alpine_image but doesn't load", error)

    def test_imports_are_followed_transitively(self):
        self.write(f"{SCENARIO}/verify_extra.yml", "- ansible.builtin.import_tasks: verify_deeper.yml\n")
        self.write(f"{SCENARIO}/verify_deeper.yml", "- ansible.builtin.command: docker run {{ molecule_helpers_alpine_image }} true\n")
        self.write(f"{SCENARIO}/verify.yml", play("aws_cli", "alpine", body=USES_AWS + "    - ansible.builtin.import_tasks: verify_extra.yml\n"))
        self.assertEqual(self.errors(), [])

    def test_a_task_file_no_play_runs_is_an_error(self):
        self.assertEqual(self.errors(), [f"{SCENARIO}/verify_extra.yml: uses molecule_helpers_*_image but no play in this scenario runs it"])


class RealRepoTests(unittest.TestCase):
    def test_the_repo_has_no_drift(self):
        self.assertEqual(mv.check(mv.REPO_ROOT), [])

    def test_the_repo_pins_every_expected_image(self):
        pins, errors = mv._pins(mv.REPO_ROOT)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(pins), ["alpine", "aws_cli", "curl", "lldap", "step_cli"])


if __name__ == "__main__":
    unittest.main()
