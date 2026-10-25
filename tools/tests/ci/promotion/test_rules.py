"""Tests for ci.promotion.rules: each rule against the paths it names, and the ones it must not fire on.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import pytest
from ci.promotion import rules


def commands(*paths: str) -> list[str]:
    return [item.rule.command for item in rules.checklist(list(paths))]


class TestGlobs:
    @pytest.mark.parametrize(
        ("path", "pattern", "expected"),
        [
            pytest.param("uv.lock", "uv.lock", True, id="exact"),
            pytest.param("sub/uv.lock", "uv.lock", False, id="exact-is-anchored"),
            pytest.param("tofu/main.tf", "tofu/**", True, id="double-star-file"),
            pytest.param("tofu/modules/vm/main.tf", "tofu/**", True, id="double-star-crosses-directories"),
            pytest.param("tofu", "tofu/**", False, id="the-directory-itself-is-not-a-file"),
            pytest.param("ansible/roles/a/x.yaml", "ansible/roles/*/x.yaml", True, id="single-star"),
            pytest.param("ansible/roles/a/b/x.yaml", "ansible/roles/*/x.yaml", False, id="single-star-stays-in-one-directory"),
            pytest.param("tofu/tests/a.tftest.hcl", "tofu/**/tests/**", True, id="double-star-slash-matches-no-directory"),
            pytest.param("tofu/modules/vm/tests/a.hcl", "tofu/**/tests/**", True, id="double-star-slash-matches-some"),
            pytest.param("tofu/modules/vm/main.tf", "tofu/**/tests/**", False, id="double-star-slash-needs-the-literal"),
            pytest.param("a.b", "a.b", True, id="dot-is-literal"),
            pytest.param("axb", "a.b", False, id="dot-is-not-a-wildcard"),
        ],
    )
    def test_matches(self, path, pattern, expected):
        assert rules.matches(path, pattern) is expected


class TestRules:
    @pytest.mark.parametrize(
        ("paths", "expected"),
        [
            pytest.param(["pyproject.toml"], ["uv sync"], id="pyproject"),
            pytest.param(["uv.lock"], ["uv sync"], id="lock"),
            pytest.param(["ansible/requirements.yml"], ["ansible-galaxy collection install -r requirements.yml"], id="galaxy"),
            pytest.param(["ansible/roles/cd_agent/tasks/main.yaml"], ["ansible-playbook playbooks/cd-agent.yaml"], id="cd-agent-role"),
            pytest.param(["ansible/playbooks/cd-agent.yaml"], ["ansible-playbook playbooks/cd-agent.yaml"], id="cd-agent-playbook"),
            pytest.param(["ansible/inventory/group_vars/cd_agent.yaml"], ["ansible-playbook playbooks/cd-agent.yaml"], id="cd-agent-vars"),
            pytest.param(["tools/cd_agent/run_job.py"], ["ansible-playbook playbooks/cd-agent.yaml"], id="cd-agent-runner"),
            pytest.param(["docker/openbao/compose.yaml.j2"], ["python3 -m openbao_utils.unseal"], id="openbao-server-image"),
            pytest.param(["docker/openbao/configs/openbao.hcl.j2"], ["python3 -m openbao_utils.unseal"], id="openbao-server-config"),
            pytest.param(["tofu/main.tf"], ["tofu -chdir=tofu plan"], id="tofu"),
            pytest.param(["tofu/modules/vm/main.tf"], ["tofu -chdir=tofu plan"], id="tofu-module"),
        ],
    )
    def test_a_path_asks_for_its_command(self, paths, expected):
        assert commands(*paths) == expected

    @pytest.mark.parametrize(
        "path",
        [
            pytest.param("docker/caddy/Dockerfile", id="image"),
            pytest.param("ansible/roles/caddy/tasks/main.yaml", id="role-the-agent-deploys"),
            # The server is the only OpenBao that can be sealed: these hold a client or a one-shot container.
            pytest.param("ansible/roles/openbao_cli/defaults/main.yaml", id="openbao-client-package"),
            pytest.param("ansible/roles/openbao/defaults/main.yaml", id="openbao-one-shot-image"),
            pytest.param("ansible/playbooks/deploy.yaml", id="openbao-chown-image-in-deploy"),
            pytest.param("docker/openbao/policies/controller.hcl", id="openbao-policy"),
            pytest.param("docker/openbao/watcher/r2_read_watcher.py", id="openbao-watcher"),
            pytest.param("ansible/inventory/group_vars/all.yaml", id="other-group-vars"),
            pytest.param("tofu/tests/vm.tftest.hcl", id="tofu-tests"),
            pytest.param("tofu/modules/vm/tests/vm.tftest.hcl", id="tofu-module-tests"),
            pytest.param("docs/topics/README.md", id="docs"),
            pytest.param("tools/ci/promotion/rules.py", id="ci-code"),
        ],
    )
    def test_a_path_the_agent_applies_asks_for_nothing(self, path):
        assert commands(path) == []

    def test_several_changes_keep_the_rule_order(self):
        assert commands("tofu/main.tf", "docker/openbao/compose.yaml.j2", "uv.lock", "ansible/roles/cd_agent/x.yaml") == [
            "uv sync",
            "ansible-playbook playbooks/cd-agent.yaml",
            "python3 -m openbao_utils.unseal",
            "tofu -chdir=tofu plan",
        ]

    def test_one_command_is_asked_once_with_every_path_that_fired_it(self):
        (item,) = rules.checklist(["uv.lock", "pyproject.toml", "uv.lock"])
        assert item.paths == ("pyproject.toml", "uv.lock")

    def test_no_changes_ask_for_nothing(self):
        assert rules.checklist([]) == []

    def test_control_a_rule_set_without_the_rule_asks_for_nothing(self):
        assert rules.checklist(["uv.lock"], rules=()) == []

    def test_every_rule_has_a_command_a_place_and_a_pattern(self, subtests):
        for rule in rules.RULES:
            with subtests.test(command=rule.command):
                assert rule.command
                assert rule.where
                assert rule.patterns

    def test_every_pattern_names_a_path_that_exists(self, subtests):
        from pathlib import Path

        root = Path(__file__).resolve().parents[4]
        for rule in rules.RULES:
            for pattern in rule.patterns:
                literal = pattern.split("*")[0].rstrip("/")
                with subtests.test(pattern=pattern):
                    assert (root / literal).exists(), f"{pattern} names nothing in the repository"
