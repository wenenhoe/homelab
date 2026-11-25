"""Tests for check_command_blocks.py, run against throwaway git repositories.
Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from doc_scripts import check_command_blocks as check


def block_errors(body: str, lang: str = "sh") -> list[str]:
    [fence] = check.fences(f"```{lang}\n{body}\n```\n")
    return [message for _, message in check.block_errors(fence)]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param('host=services\nssh "$host" uptime', id="variable"),
        pytest.param("read -rsp 'token: ' TOKEN; echo", id="prompt-ends-block"),
        pytest.param("cd tools\nread -r -p 'id: ' rid && python3 -m openbao_utils.shell \"$rid\"; unset rid", id="prompt-shares-its-line"),
        pytest.param("# controller: it waits\nssh security", id="session-alone"),
        pytest.param("ssh -t security\n# paste <this> once the prompt is back", id="comment-is-not-read"),
        pytest.param("echo 'a # b'  # <c>\necho ${#list[@]} <<< \"$x\"\nbao policy write p - < p.hcl", id="redirections"),
        pytest.param("docker inspect --format '{{json .HostConfig}}' web\ndocker info --format '{{.Driver}}'", id="go-template"),
        pytest.param('printf %s "$k" | { read -r line; echo "$line"; }\nIFS= read -r x < file\necho done', id="read-not-from-terminal"),
        pytest.param("until [[ $url == https://* ]]; do\n  read -r url\ndone", id="prompt-closing-a-loop"),
        pytest.param("read -rs TOKEN; export TOKEN\n", id="trailing-blank-line"),
        pytest.param('export BAO_TOKEN\nexport BAO_TOKEN="$t"\nAPI_TOKEN=$(cat f)\nprintf \'API_KEY=%q\\n\' "$key"\ntoken_ttl=1h', id="secret-from-elsewhere"),
        pytest.param("go test ./...", id="path-ellipsis"),
    ],
)
def test_a_safe_block_passes(body: str) -> None:
    assert block_errors(body) == []


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param("ssh <host> uptime", "placeholder `<host>`", id="angle-brackets"),
        pytest.param("bao write x \\\n  role=<role name>", "placeholder `<role name>`", id="continued-line"),
        pytest.param("export SAN=openbao.{{ caddy_domain }}", "placeholder `{{ caddy_domain }}`", id="template-variable"),
        pytest.param("run -e ca_file=... -e x=1", "placeholder `...`", id="ellipsis"),
        pytest.param("# [1/2] one\nls\n# [2/2] two\nls", "second segment", id="two-segments"),
        pytest.param('read -r host\nssh "$host" uptime', "waits for input", id="read"),
        pytest.param("ssh security\nls", "waits for input", id="ssh"),
        pytest.param('ssh -t "root@$node"\nls', "waits for input", id="ssh-variable-host"),
        pytest.param("cd tools && python3 -m openbao_utils.shell id\nbao status", "waits for input", id="openbao-shell"),
        pytest.param("gpg --full-generate-key\ngpg --list-keys", "waits for input", id="gpg"),
        pytest.param("docker run --rm -it alpine sh\nls", "waits for input", id="docker-it"),
        pytest.param("export BAO_TOKEN=s.abc123", "literal value", id="literal-secret"),
        pytest.param('curl -su "admin:$PW" https://example.test', "curl -u", id="curl-bundled-u"),
        pytest.param("curl --user admin https://example.test", "curl -u", id="curl-user"),
    ],
)
def test_an_unsafe_block_is_refused(body: str, expected: str) -> None:
    [error] = block_errors(body)
    assert expected in error


def test_only_shell_blocks_are_read_for_commands() -> None:
    assert block_errors("AllowUsers <admin>", lang="text") == []


def test_a_fence_without_a_language_is_refused() -> None:
    [error] = block_errors("ls", lang="")
    assert "names no language" in error


def test_a_fence_indented_in_a_list_is_found() -> None:
    [fence] = check.fences("1. Step:\n\n   ```sh\n   ssh <host>\n   ```\n")
    assert fence.lang == "sh"
    assert check.block_errors(fence)[0][0] == 4


def test_a_longer_fence_holds_shorter_ones() -> None:
    [fence] = check.fences("````text\n```\nssh <host>\n```\n````\n")
    assert fence.lang == "text"


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_the_run_reads_markdown_outside_decision_records(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, capture_output=True)
    bad = "# T\n\n```sh\nssh <host>\n```\n"
    write(root, "docs/topics/a.md", bad)
    write(root, "docs/decisions/0001-x/revision-000.md", bad)
    write(root, "notes.txt", bad)

    assert check.main(["--root", str(root)]) == 1
    assert [line.split(": ")[0] for line in capsys.readouterr().out.splitlines()] == ["::error::docs/topics/a.md:4"]


def test_a_clean_tree_passes(root: Path) -> None:
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, capture_output=True)
    write(root, "README.md", "```sh\nls\n```\n")

    assert check.main(["--root", str(root)]) == 0
