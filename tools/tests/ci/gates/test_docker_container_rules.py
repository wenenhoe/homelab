"""Tests for ci.gates.docker_container_rules: one case per rule, then the real task files.

Run via `uv run pytest tests/ -v` from tools/.
"""

from __future__ import annotations

import io
import textwrap
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest
from ci.gates import docker_container_rules as rules

PATH = "ansible/roles/app/tasks/main.yaml"
NAME = "Start the helper"
BASELINE = """\
    cap_drop:
      - ALL
    security_opts:
      - no-new-privileges:true
"""


def task(extra: str = "", name: str = NAME, baseline: str = BASELINE, module: str = "community.docker.docker_container") -> str:
    return f"- name: {name}\n  {module}:\n    name: helper\n    image: example\n{extra}{baseline}"


def listing(*entries: tuple[str, str, str]) -> dict:
    """EXCEPTIONS-shaped mapping of (file, task name, setting) entries, each with a reason."""
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
    def test_a_task_with_the_pair_and_nothing_wider_passes(self):
        assert run(task()) == ([], set())

    def test_the_short_module_name_is_read_too(self):
        assert run(task(module="docker_container", baseline=""))[0] == ["cap-drop", "no-new-privileges"]

    def test_missing_cap_drop_is_refused(self):
        text = task(baseline="    security_opts:\n      - no-new-privileges:true\n")
        assert run(text)[0] == ["cap-drop"]

    @pytest.mark.parametrize("drop", ["[NET_RAW]", "[ALL, NET_RAW]", "[]"], ids=["other-capability", "all-with-another", "empty"])
    def test_cap_drop_that_is_not_exactly_all_is_refused(self, drop):
        text = task(baseline=f"    cap_drop: {drop}\n    security_opts: [no-new-privileges:true]\n")
        assert run(text)[0] == ["cap-drop"]

    def test_missing_no_new_privileges_is_refused(self):
        assert run(task(baseline="    cap_drop: [ALL]\n"))[0] == ["no-new-privileges"]

    def test_no_new_privileges_set_to_false_is_refused(self):
        text = task(baseline="    cap_drop: [ALL]\n    security_opts: [no-new-privileges:false]\n")
        assert set(run(text)[0]) == {"no-new-privileges", "exception"}

    def test_the_equals_form_of_no_new_privileges_counts(self):
        assert run(task(baseline="    cap_drop: [ALL]\n    security_opts: [no-new-privileges=true]\n")) == ([], set())

    def test_every_task_is_judged_not_only_the_first(self):
        assert run(task() + task(baseline="", name="Other"))[0] == ["cap-drop", "no-new-privileges"]

    def test_network_mode_none_is_not_an_exception(self):
        assert run(task("    network_mode: none\n")) == ([], set())


WIDER = [
    pytest.param("    capabilities:\n      - CHOWN\n", "cap_add:CHOWN", id="capability"),
    pytest.param("    capabilities:\n      - cap_chown\n", "cap_add:CHOWN", id="capability-spelt-with-prefix-and-lowercase"),
    pytest.param("    privileged: true\n", "privileged", id="privileged"),
    pytest.param("    privileged: yes\n", "privileged", id="privileged-yes"),
    pytest.param("    network_mode: host\n", "network_mode:host", id="host-network"),
    pytest.param("    pid_mode: host\n", "pid:host", id="host-pid"),
    pytest.param("    ipc_mode: host\n", "ipc:host", id="host-ipc"),
    pytest.param("    uts: host\n", "uts:host", id="host-uts"),
    pytest.param("    userns_mode: host\n", "userns_mode:host", id="host-userns"),
    pytest.param("    devices:\n      - /dev/dri:/dev/dri\n", "devices", id="devices"),
    pytest.param("    volumes:\n      - /var/run/docker.sock:/var/run/docker.sock:ro\n", "docker-socket", id="socket-in-volumes"),
    pytest.param("    volumes:\n      - '{{ sock }}:/run/docker.sock'\n", "docker-socket", id="socket-with-a-templated-source"),
    pytest.param("    mounts:\n      - type: bind\n        source: /run/docker.sock\n        target: /sock\n", "docker-socket", id="socket-in-mounts"),
    pytest.param(
        "    mounts:\n      - type: bind\n        source: /run/docker.sock/\n        target: /sock\n", "docker-socket", id="socket-with-trailing-slash"
    ),
]


class TestEachWideningNeedsAReason:
    @pytest.mark.parametrize(("extra", "setting"), WIDER)
    def test_it_is_refused_without_an_exception(self, extra, setting):
        assert run(task(extra))[0] == ["exception"]

    @pytest.mark.parametrize(("extra", "setting"), WIDER)
    def test_it_passes_with_an_exception_and_the_exception_is_used(self, extra, setting):
        key = (PATH, NAME, setting)
        assert run(task(extra), listing(key)) == ([], {key})

    def test_an_exception_for_one_task_does_not_cover_another(self):
        text = task("    capabilities: [CHOWN]\n", name="Other")
        assert run(text, listing((PATH, NAME, "cap_add:CHOWN")))[0] == ["exception"]

    def test_an_exception_for_one_file_does_not_cover_another(self):
        text = task("    capabilities: [CHOWN]\n")
        assert run(text, listing(("ansible/roles/else/tasks/main.yaml", NAME, "cap_add:CHOWN")))[0] == ["exception"]

    def test_each_capability_needs_its_own_entry(self):
        text = task("    capabilities: [CHOWN, FOWNER]\n")
        assert run(text, listing((PATH, NAME, "cap_add:CHOWN")))[0] == ["exception"]

    def test_a_security_opt_beyond_the_baseline_needs_an_entry(self):
        baseline = "    cap_drop: [ALL]\n    security_opts:\n      - no-new-privileges:true\n      - seccomp:unconfined\n"
        text = task(baseline=baseline)
        assert run(text)[0] == ["exception"]
        key = (PATH, NAME, "security_opt:seccomp:unconfined")
        assert run(text, listing(key)) == ([], {key})

    @pytest.mark.parametrize(
        "extra", ["    privileged: false\n", "    network_mode: bridge\n", "    volumes:\n      - data:/data\n"], ids=["privileged-false", "bridge", "volume"]
    )
    def test_a_setting_that_is_not_a_widening_is_not_an_exception(self, extra):
        assert run(task(extra)) == ([], set())


class TestJinja:
    @pytest.mark.parametrize(
        "text",
        [
            '    cap_drop: "{{ drops }}"\n    security_opts: [no-new-privileges:true]\n',
            '    cap_drop: [ALL]\n    security_opts: "{{ opts }}"\n',
            '    cap_drop: [ALL]\n    security_opts: [no-new-privileges:true]\n    capabilities: "{{ caps }}"\n',
        ],
        ids=["cap_drop", "security_opts", "capabilities"],
    )
    def test_a_list_parameter_that_is_only_an_expression_is_refused(self, text):
        assert run(task(baseline=text))[0] == ["jinja"]

    def test_an_entry_that_is_an_expression_is_refused(self):
        assert run(task('    capabilities:\n      - "{{ cap }}"\n'))[0] == ["jinja"]

    @pytest.mark.parametrize("key", ["privileged", "network_mode", "pid_mode", "devices", "volumes"])
    def test_a_judged_value_that_is_an_expression_is_refused(self, key):
        assert run(task(f'    {key}: "{{{{ x }}}}"\n'))[0] == ["jinja"]

    def test_an_expression_inside_an_ordinary_value_is_not_refused(self):
        text = task('    labels:\n      sha: "{{ sha }}"\n    volumes:\n      - "{{ vol }}:/data"\n    command: ["echo", "{{ x }}"]\n')
        assert run(text) == ([], set())

    def test_a_state_that_is_an_expression_is_refused(self):
        assert run(task('    state: "{{ wanted }}"\n'))[0] == ["jinja"]

    def test_a_tagged_value_is_read_as_its_plain_value(self):
        text = task('    env:\n      TOKEN: !vault |\n        $ANSIBLE_VAULT;1.1;AES256\n        6162\n      RAW: !unsafe "{{ x }}"\n')
        assert run(text) == ([], set())


class TestWhichTasksAreJudged:
    @pytest.mark.parametrize("state", ["started", "present", "stopped", "healthy"])
    def test_a_state_that_creates_a_container_is_judged(self, state):
        assert run(task(f"    state: {state}\n", baseline=""))[0] == ["cap-drop", "no-new-privileges"]

    def test_state_absent_is_skipped(self):
        assert run(task("    state: absent\n", baseline="")) == ([], set())

    def test_a_task_in_block_rescue_and_always_is_judged(self):
        for section in ("block", "rescue", "always"):
            inner = textwrap.indent(task(baseline="", name="Inner"), "    ")
            text = f"- name: Outer\n  {section}:\n{inner}"
            assert run(text)[0] == ["cap-drop", "no-new-privileges"], section

    def test_a_task_in_a_play_is_judged(self):
        text = (
            "- hosts: all\n  tasks:\n"
            + textwrap.indent(task(baseline=""), "    ")
            + "  handlers:\n"
            + textwrap.indent(task(baseline="", name="Handler"), "    ")
        )
        assert run(text)[0] == ["cap-drop", "no-new-privileges"] * 2

    def test_a_docker_container_parameter_named_command_is_not_a_task(self):
        assert run(task("    command: [sh, -c, docker run alpine]\n")) == ([], set())

    def test_other_modules_are_ignored(self):
        info = "- name: Info\n  community.docker.docker_container_info:\n    name: x\n"
        exec_ = "- name: Exec\n  community.docker.docker_container_exec:\n    container: x\n    command: id\n"
        assert run(info + exec_) == ([], set())


class TestShapeOfTheFile:
    def test_a_repeated_key_is_refused(self):
        assert run("- name: A\n  community.docker.docker_container:\n    name: a\n    image: x\n    image: y\n")[0] == ["unreadable"]

    def test_broken_yaml_is_refused(self):
        assert run("- name: [\n")[0] == ["unreadable"]

    def test_two_checked_tasks_with_one_name_are_refused(self):
        assert run(task() + task())[0] == ["duplicate-name"]

    def test_two_tasks_with_one_name_are_fine_when_one_is_skipped(self):
        assert run(task() + task("    state: absent\n", baseline="")) == ([], set())

    def test_a_checked_task_needs_a_name(self):
        text = "- community.docker.docker_container:\n    name: helper\n    image: x\n" + BASELINE
        assert run(text)[0] == ["task-name"]

    def test_free_form_parameters_are_refused(self):
        assert run("- name: A\n  community.docker.docker_container: name=a image=x\n")[0] == ["module-shape"]

    def test_a_file_without_tasks_passes(self):
        assert run("---\nfoo: bar\n") == ([], set())

    def test_every_document_of_a_file_is_read(self):
        assert run(task() + "---\n" + task(baseline="", name="Second"))[0] == ["cap-drop", "no-new-privileges"]


class TestDockerRun:
    @pytest.mark.parametrize("module", ["ansible.builtin.command", "ansible.builtin.shell", "command", "shell"])
    def test_docker_run_in_a_command_or_shell_task_is_refused(self, module):
        assert run(f"- name: Run\n  {module}: docker run --rm alpine true\n")[0] == ["docker-run"]

    @pytest.mark.parametrize(
        "command",
        [
            "sudo docker run alpine",
            "echo ok && docker run alpine",
            "docker container run alpine",
            "/usr/bin/docker run alpine",
            "$(docker run alpine)",
        ],
        ids=["sudo", "after-and", "container-run", "full-path", "substitution"],
    )
    def test_the_usual_spellings_are_refused(self, command):
        assert run(f"- name: Run\n  ansible.builtin.shell: {command!r}\n")[0] == ["docker-run"]

    def test_the_cmd_and_argv_forms_are_read(self):
        assert run("- name: A\n  ansible.builtin.command:\n    cmd: docker run alpine\n")[0] == ["docker-run"]
        assert run("- name: B\n  ansible.builtin.command:\n    argv: [docker, run, alpine]\n")[0] == ["docker-run"]

    def test_a_multi_line_script_is_read_line_by_line(self):
        text = "- name: Run\n  ansible.builtin.shell: |\n    set -e\n    docker run alpine\n"
        assert run(text)[0] == ["docker-run"]

    def test_a_comment_is_not_a_command(self):
        text = "- name: Run\n  ansible.builtin.shell: |\n    # docker run alpine\n    echo ok  # docker run alpine\n"
        assert run(text) == ([], set())

    def test_other_docker_commands_are_allowed(self):
        assert run("- name: Run\n  ansible.builtin.command: docker volume ls\n") == ([], set())

    def test_the_word_run_elsewhere_is_allowed(self):
        assert run("- name: Run\n  ansible.builtin.shell: echo docker run is banned\n") == ([], set())


def write(root: Path, rel: str, text: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


class TestAcrossTheRepo:
    def test_the_scope_is_playbooks_and_role_tasks_and_handlers_but_not_molecule(self, tmp_path):
        for rel in (
            "ansible/playbooks/a.yaml",
            "ansible/playbooks/sub/b.yml",
            "ansible/roles/r/tasks/main.yaml",
            "ansible/roles/r/tasks/sub/more.yml",
            "ansible/roles/r/handlers/main.yaml",
            "ansible/roles/r/molecule/default/converge.yaml",
            "ansible/roles/r/tasks/molecule/x.yaml",
            "ansible/roles/molecule_helpers/tasks/start.yaml",
            "ansible/roles/r/templates/t.yaml",
            "ansible/roles/r/defaults/main.yaml",
            "docker/a/compose.yaml",
        ):
            write(tmp_path, rel, task())
        assert rules.scoped_files(tmp_path) == [
            "ansible/playbooks/a.yaml",
            "ansible/playbooks/sub/b.yml",
            "ansible/roles/r/handlers/main.yaml",
            "ansible/roles/r/tasks/main.yaml",
            "ansible/roles/r/tasks/sub/more.yml",
        ]

    def test_a_violation_in_a_scoped_file_is_found(self, tmp_path):
        write(tmp_path, PATH, task(baseline=""))
        assert [violation.rule for violation in rules.check(tmp_path, {})] == ["cap-drop", "no-new-privileges"]

    def test_a_violation_in_a_molecule_file_is_not_looked_for(self, tmp_path):
        write(tmp_path, "ansible/roles/r/molecule/default/prepare.yaml", task(baseline=""))
        assert rules.check(tmp_path, {}) == []

    def test_an_exception_nothing_uses_is_reported_as_stale(self, tmp_path):
        write(tmp_path, PATH, task())
        found = rules.check(tmp_path, listing((PATH, NAME, "cap_add:CHOWN"), (PATH, "Gone", "privileged")))
        assert [(violation.rule, violation.task) for violation in found] == [("stale-exception", "Gone"), ("stale-exception", NAME)]

    def test_an_exception_for_a_file_that_is_gone_is_reported_as_stale(self, tmp_path):
        write(tmp_path, PATH, task())
        found = rules.check(tmp_path, listing(("ansible/roles/old/tasks/main.yaml", NAME, "privileged")))
        assert [violation.rule for violation in found] == ["stale-exception"]

    def test_an_exception_for_a_task_that_is_now_absent_is_stale(self, tmp_path):
        write(tmp_path, PATH, task("    state: absent\n    privileged: true\n", baseline=""))
        found = rules.check(tmp_path, listing((PATH, NAME, "privileged")))
        assert [violation.rule for violation in found] == ["stale-exception"]

    def test_a_used_exception_is_not_stale(self, tmp_path):
        write(tmp_path, PATH, task("    privileged: true\n"))
        assert rules.check(tmp_path, listing((PATH, NAME, "privileged"))) == []

    def test_the_name_is_keyed_by_its_raw_jinja_text(self, tmp_path):
        name = '"Remove file(s) from the volume ({{ volume_rm_full_name }})"'
        write(tmp_path, PATH, task("    privileged: true\n", name=name))
        raw = "Remove file(s) from the volume ({{ volume_rm_full_name }})"
        assert rules.check(tmp_path, listing((PATH, raw, "privileged"))) == []


class TestRealRepo:
    def test_every_task_keeps_the_baseline_and_every_exception_is_used(self):
        assert rules.check(rules.REPO_ROOT) == []

    def test_the_scope_reaches_the_files_it_is_meant_to(self):
        files = rules.scoped_files(rules.REPO_ROOT)
        assert "ansible/playbooks/bootstrap-security.yaml" in files
        assert "ansible/roles/restore/tasks/main.yaml" in files
        assert not any("/molecule/" in path or "molecule_helpers" in path for path in files)

    def test_removing_any_exception_makes_the_real_tree_fail(self, subtests):
        for path, tasks in rules.EXCEPTIONS.items():
            for name, settings in tasks.items():
                for setting in settings:
                    with subtests.test(path=path, task=name, setting=setting):
                        trimmed = {p: {n: dict(s) for n, s in t.items()} for p, t in rules.EXCEPTIONS.items()}
                        del trimmed[path][name][setting]
                        found = rules.check(rules.REPO_ROOT, trimmed)
                        assert [(v.path, v.task, v.rule) for v in found] == [(path, name, "exception")]

    def test_every_exception_names_a_reason(self):
        reasons = [reason for tasks in rules.EXCEPTIONS.values() for settings in tasks.values() for reason in settings.values()]
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
        violation = rules.Violation(PATH, NAME, "cap-drop", "must set `cap_drop: [ALL]`")
        monkeypatch.setattr(rules, "check", lambda root: [violation])
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            assert rules.main() == 1
        assert f"::error::{PATH}: {NAME}: must set `cap_drop: [ALL]` [cap-drop]" in err.getvalue()
        assert "1 hardening violation(s)" in err.getvalue()
