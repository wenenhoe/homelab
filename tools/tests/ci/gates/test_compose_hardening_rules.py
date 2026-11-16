"""Tests for ci.gates.compose_hardening_rules: one case per rule, then the real compose files.

Run via `uv run pytest tests/ -v` from tools/.
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest
from ci.gates import compose_hardening_rules as rules

PATH = "docker/app/compose.yaml"
BASELINE = """\
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
"""


def service(extra: str = "", name: str = "app", baseline: str = BASELINE) -> str:
    return f"services:\n  {name}:\n    image: example\n{extra}{baseline}"


def listing(*entries: tuple[str, str, str]) -> dict:
    """EXCEPTIONS-shaped mapping of (file, service, setting) entries, each with a reason."""
    nested: dict = {}
    for path, name, setting in entries:
        nested.setdefault(path, {}).setdefault(name, {})[setting] = "why"
    return nested


def run(text: str, exceptions: dict | None = None, path: str = PATH):
    """(rule ids broken, exceptions used) for one file."""
    used: set = set()
    found = rules.check_text(path, text, exceptions or {}, used)
    return [violation.rule for violation in found], used


class TestBaseline:
    def test_a_service_with_the_pair_and_nothing_wider_passes(self):
        assert run(service()) == ([], set())

    def test_missing_cap_drop_is_refused(self):
        text = service(baseline="    security_opt:\n      - no-new-privileges:true\n")
        assert run(text)[0] == ["cap-drop"]

    def test_cap_drop_that_does_not_name_all_is_refused(self):
        text = service(baseline="    cap_drop:\n      - NET_RAW\n    security_opt:\n      - no-new-privileges:true\n")
        assert run(text)[0] == ["cap-drop"]

    def test_missing_no_new_privileges_is_refused(self):
        assert run(service(baseline="    cap_drop:\n      - ALL\n"))[0] == ["no-new-privileges"]

    def test_no_new_privileges_set_to_false_is_refused(self):
        text = service(baseline="    cap_drop:\n      - ALL\n    security_opt:\n      - no-new-privileges:false\n")
        assert set(run(text)[0]) == {"no-new-privileges", "exception"}

    def test_the_equals_form_of_no_new_privileges_counts(self):
        text = service(baseline="    cap_drop: [ALL]\n    security_opt: [no-new-privileges=true]\n")
        assert run(text) == ([], set())

    def test_every_service_is_judged_not_only_the_first(self):
        text = service() + "  other:\n    image: example\n"
        assert run(text)[0] == ["cap-drop", "no-new-privileges"]

    def test_network_mode_none_is_not_an_exception(self):
        assert run(service("    network_mode: none\n")) == ([], set())


WIDER = [
    pytest.param("    cap_add:\n      - CHOWN\n", "cap_add:CHOWN", id="cap_add"),
    pytest.param("    cap_add:\n      - cap_chown\n", "cap_add:CHOWN", id="cap_add-spelt-with-prefix-and-lowercase"),
    pytest.param("    privileged: true\n", "privileged", id="privileged"),
    pytest.param("    network_mode: host\n", "network_mode:host", id="host-network"),
    pytest.param("    pid: host\n", "pid:host", id="host-pid"),
    pytest.param("    ipc: host\n", "ipc:host", id="host-ipc"),
    pytest.param("    uts: host\n", "uts:host", id="host-uts"),
    pytest.param("    userns_mode: host\n", "userns_mode:host", id="host-userns"),
    pytest.param("    devices:\n      - /dev/dri:/dev/dri\n", "devices", id="devices"),
    pytest.param("    volumes:\n      - /var/run/docker.sock:/var/run/docker.sock:ro\n", "docker-socket", id="socket-short-form"),
    pytest.param("    volumes:\n      - type: bind\n        source: /run/docker.sock\n        target: /sock\n", "docker-socket", id="socket-long-form"),
    pytest.param("    volumes:\n      - /var/run/docker.sock/:/sock\n", "docker-socket", id="socket-with-trailing-slash"),
]


class TestEachWideningNeedsAReason:
    @pytest.mark.parametrize(("extra", "setting"), WIDER)
    def test_it_is_refused_without_an_exception(self, extra, setting):
        assert run(service(extra))[0] == ["exception"]

    @pytest.mark.parametrize(("extra", "setting"), WIDER)
    def test_it_passes_with_an_exception_and_the_exception_is_used(self, extra, setting):
        key = (PATH, "app", setting)
        assert run(service(extra), listing(key)) == ([], {key})

    def test_an_exception_for_one_service_does_not_cover_another(self):
        text = service("    cap_add:\n      - CHOWN\n", name="other")
        assert run(text, listing((PATH, "app", "cap_add:CHOWN")))[0] == ["exception"]

    def test_an_exception_for_one_file_does_not_cover_another(self):
        text = service("    cap_add:\n      - CHOWN\n")
        assert run(text, listing(("docker/else/compose.yaml", "app", "cap_add:CHOWN")), path=PATH)[0] == ["exception"]

    def test_each_capability_needs_its_own_entry(self):
        text = service("    cap_add:\n      - CHOWN\n      - FOWNER\n")
        assert run(text, listing((PATH, "app", "cap_add:CHOWN")))[0] == ["exception"]

    def test_a_security_opt_value_beyond_the_baseline_needs_an_entry(self):
        baseline = "    cap_drop: [ALL]\n    security_opt:\n      - no-new-privileges:true\n      - seccomp:unconfined\n"
        text = service(baseline=baseline)
        assert run(text)[0] == ["exception"]
        key = (PATH, "app", "security_opt:seccomp:unconfined")
        assert run(text, listing(key)) == ([], {key})

    def test_privileged_false_is_not_a_widening(self):
        assert run(service("    privileged: false\n")) == ([], set())


class TestJinja:
    def test_an_expression_is_replaced_and_the_rest_is_read(self):
        text = service("    labels:\n      sha: \"{{ lookup('file', 'x') | hash('sha256') }}\"\n")
        assert run(text) == ([], set())

    def test_a_statement_on_its_own_line_is_dropped_and_its_body_read_once(self):
        text = (
            "services:\n{% if flag %}\n  a:\n    image: x\n" + BASELINE + "{% endif %}\n{% for v in vols %}\n  b:\n    image: x\n" + BASELINE + "{% endfor %}\n"
        )
        assert run(text) == ([], set())

    def test_a_service_inside_an_if_block_is_still_judged(self):
        text = "services:\n{% if flag %}\n  a:\n    image: x\n    cap_add: [CHOWN]\n" + BASELINE + "{% endif %}\n"
        assert run(text)[0] == ["exception"]

    def test_a_jinja_comment_is_ignored(self):
        assert run("{# a note #}\n" + service()) == ([], set())

    def test_a_statement_that_shares_a_line_is_refused(self):
        assert run("services:\n  a:\n    image: {% if x %}y{% endif %}\n")[0] == ["unreadable"]

    def test_a_generated_key_is_a_plain_name(self):
        text = service() + "volumes:\n  {{ app.name }}_{{ vol }}:\n    external: true\n"
        assert run(text) == ([], set())


class TestShapeOfTheFile:
    @pytest.mark.parametrize(
        ("text", "rule"),
        [
            pytest.param("name: x\n", "no-services", id="no-services"),
            pytest.param("services: {}\n", "no-services", id="empty-services"),
            pytest.param("- a\n- b\n", "no-services", id="not-a-mapping"),
            pytest.param("include:\n  - other.yaml\n" + service(), "include", id="include"),
            pytest.param("services:\n  a: just-text\n", "service-shape", id="service-not-a-mapping"),
            pytest.param("services:\n  a:\n    image: x\n  a:\n    image: y\n", "unreadable", id="repeated-service"),
            pytest.param("services: [\n", "unreadable", id="broken-yaml"),
        ],
    )
    def test_the_file_is_refused(self, text, rule):
        assert run(text)[0] == [rule]

    def test_extends_is_refused_because_its_settings_are_elsewhere(self):
        text = service("    extends:\n      file: base.yaml\n      service: base\n")
        assert run(text)[0] == ["extends"]

    def test_a_merge_key_brings_its_settings_into_the_judgement(self):
        text = "x-wide: &wide\n  cap_add: [CHOWN]\n" + "services:\n  a:\n    <<: *wide\n    image: x\n" + BASELINE
        assert run(text)[0] == ["exception"]


def write(root: Path, rel: str, text: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


class TestAcrossTheRepo:
    def test_the_scope_is_docker_and_role_templates_but_not_molecule(self, tmp_path):
        for rel in (
            "docker/a/compose.yaml",
            "docker/a/compose.restore.yaml",
            "docker/b/compose.yaml.j2",
            "ansible/roles/r/templates/compose.yaml.j2",
            "docker/a/not-compose.yaml",
            "ansible/roles/r/molecule/default/compose.yaml",
            "ansible/roles/r/tasks/compose.yaml",
            "scratch/compose.yaml",
        ):
            write(tmp_path, rel, service())
        assert rules.scoped_files(tmp_path) == [
            "ansible/roles/r/templates/compose.yaml.j2",
            "docker/a/compose.restore.yaml",
            "docker/a/compose.yaml",
            "docker/b/compose.yaml.j2",
        ]

    def test_an_exception_nothing_uses_is_reported_as_stale(self, tmp_path):
        write(tmp_path, PATH, service())
        found = rules.check(tmp_path, listing((PATH, "app", "cap_add:CHOWN"), (PATH, "gone", "privileged")))
        assert [(violation.rule, violation.service) for violation in found] == [("stale-exception", "app"), ("stale-exception", "gone")]

    def test_an_exception_for_a_file_that_is_gone_is_reported_as_stale(self, tmp_path):
        write(tmp_path, PATH, service())
        found = rules.check(tmp_path, listing(("docker/old/compose.yaml", "app", "privileged")))
        assert [violation.rule for violation in found] == ["stale-exception"]

    def test_a_used_exception_is_not_stale(self, tmp_path):
        write(tmp_path, PATH, service("    privileged: true\n"))
        assert rules.check(tmp_path, listing((PATH, "app", "privileged"))) == []


class TestRealRepo:
    def test_every_compose_file_keeps_the_baseline_and_every_exception_is_used(self):
        assert rules.check(rules.REPO_ROOT) == []

    def test_the_scope_reaches_the_files_it_is_meant_to(self):
        files = rules.scoped_files(rules.REPO_ROOT)
        assert "docker/caddy/compose.yaml" in files
        assert "docker/minecraft/compose.restore.yaml" in files
        assert "ansible/roles/backup_agent/templates/compose.yaml.j2" in files
        assert not any("/molecule/" in path for path in files)

    def test_every_exception_names_a_reason(self):
        reasons = [reason for services in rules.EXCEPTIONS.values() for settings in services.values() for reason in settings.values()]
        assert reasons
        assert all(reason.strip() for reason in reasons)

    def test_every_exception_names_a_file_in_scope(self):
        assert set(rules.EXCEPTIONS) <= set(rules.scoped_files(rules.REPO_ROOT))


class TestMain:
    def test_main_reports_success_on_the_real_repo(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            assert rules.main() == 0
        assert "keeps the hardening baseline" in out.getvalue()
        assert err.getvalue() == ""

    def test_main_prints_each_violation_and_fails(self, monkeypatch):
        violation = rules.Violation(PATH, "app", "cap-drop", "must set `cap_drop: [ALL]`")
        monkeypatch.setattr(rules, "check", lambda root: [violation])
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            assert rules.main() == 1
        assert f"::error::{PATH}: app: must set `cap_drop: [ALL]` [cap-drop]" in err.getvalue()
        assert "1 hardening violation(s)" in err.getvalue()
