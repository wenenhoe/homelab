"""Tests for check_mermaid.py: finding fenced blocks, the container command, the
renderer's message and the check's exit status. The container run is replaced by a
double bound to subprocess.run; the stderr below is the pinned CLI's real output for
a block that does not parse. Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from unittest.mock import create_autospec

import pytest
from _doc_fixtures import GitRepo
from doc_scripts import check_mermaid as cli

PARSE_ERROR_STDERR = """
Error: Parse error on line 3:
...  a --> b -->    c [[[
----------------------^
Expecting 'SEMI', 'NEWLINE', 'SPACE', 'EOF', 'AMP', 'COLON', got 'SUBROUTINESTART'
Parser.parseError (https://mermaid-cli-intercept.invalid/home/mermaidcli/node_modules/mermaid/dist/chunks/mermaid.esm/chunk-T3ODRKFR.mjs:1561:21)
Parser.parse (https://mermaid-cli-intercept.invalid/home/mermaidcli/node_modules/mermaid/dist/chunks/mermaid.esm/chunk-T3ODRKFR.mjs:1633:16)
    at #evaluate (file:///home/mermaidcli/node_modules/puppeteer-core/lib/puppeteer/cdp/ExecutionContext.js:402:19)
    at async ExecutionContext.evaluate (file:///home/mermaidcli/node_modules/puppeteer-core/lib/puppeteer/cdp/ExecutionContext.js:288:16)
"""
PARSE_ERROR_MESSAGE = """Parse error on line 3:
...  a --> b -->    c [[[
----------------------^
Expecting 'SEMI', 'NEWLINE', 'SPACE', 'EOF', 'AMP', 'COLON', got 'SUBROUTINESTART'"""

# The pinned CLI's output for a block whose first line names no diagram type.
UNKNOWN_DIAGRAM_STDERR = """
UnknownDiagramError: No diagram type detected matching given configuration for text: this is not a diagram [[[
flowchart TD
    a --> b

    at $eval ($eval at renderMermaid (file:///home/mermaidcli/node_modules/@mermaid-js/mermaid-cli/src/index.js:689:33), <anonymous>:43:47)
    at #evaluate (file:///home/mermaidcli/node_modules/puppeteer-core/lib/puppeteer/cdp/ExecutionContext.js:402:19)
"""
UNKNOWN_DIAGRAM_MESSAGE = """UnknownDiagramError: No diagram type detected matching given configuration for text: this is not a diagram [[[
flowchart TD
    a --> b"""

GOOD = "flowchart TD\n    a --> b"
BAD = "flowchart TD\n    a --> b -->\n    c [[["


def fence(body: str, info: str = "mermaid") -> str:
    return f"```{info}\n{body}\n```\n"


def completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def docker(failing: dict[str, subprocess.CompletedProcess[str]] | None = None, pull_result: subprocess.CompletedProcess[str] | None = None):
    """A subprocess.run stand-in: pulls succeed and blocks render, except the block texts in `failing`."""
    failing = failing or {}

    def fake(args, **kwargs):
        if args[:2] == ["docker", "pull"]:
            return pull_result or completed()
        return failing.get(kwargs["input"], completed())

    return create_autospec(subprocess.run, side_effect=fake)


def run_inputs(runner) -> list[str]:
    return [call.kwargs["input"] for call in runner.call_args_list if call.args[0][:2] == ["docker", "run"]]


class TestFindBlocks:
    def test_a_mermaid_fence_is_a_block_with_its_text_and_line(self):
        blocks = cli.find_blocks(f"# Title\n\n{fence(GOOD)}", "docs/a.md")
        assert blocks == [cli.Block("docs/a.md", 3, GOOD)]

    def test_every_block_in_a_file_is_found_with_its_own_line(self):
        text = f"{fence(GOOD)}\ntext\n\n{fence(BAD)}"
        assert [(b.line, b.text) for b in cli.find_blocks(text, "a.md")] == [(1, GOOD), (8, BAD)]

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param(fence("print(1)", "python"), id="another-language"),
            pytest.param(fence("a --> b", ""), id="no-info-string"),
            pytest.param(fence("a --> b", "mermaidx"), id="info-string-only-starts-with-the-word"),
            pytest.param("A ```mermaid``` span in a sentence.\n", id="inline-code-span"),
            pytest.param(f"````markdown\n{fence(GOOD)}````\n", id="quoted-in-a-longer-backtick-fence"),
            pytest.param(f"~~~markdown\n{fence(GOOD)}~~~\n", id="quoted-in-a-tilde-fence"),
            pytest.param("no fences here\n", id="no-fence"),
        ],
    )
    def test_text_that_is_not_a_mermaid_fence_gives_no_block(self, text):
        assert cli.find_blocks(text, "a.md") == []

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            pytest.param("~~~mermaid\nflowchart TD\n~~~\n", "flowchart TD", id="tilde-fence"),
            pytest.param("```mermaid title=Flow\nflowchart TD\n```\n", "flowchart TD", id="attributes-after-the-word"),
            pytest.param("````mermaid\nflowchart TD\n```\n    a --> b\n````\n", "flowchart TD\n```\n    a --> b", id="a-shorter-fence-line-does-not-close"),
            pytest.param(
                "```mermaid\nflowchart TD\n~~~\n    a --> b\n```\n", "flowchart TD\n~~~\n    a --> b", id="a-different-fence-character-does-not-close"
            ),
            pytest.param("- item\n\n  ```mermaid\n  flowchart TD\n      a --> b\n  ```\n", "flowchart TD\n    a --> b", id="indented-in-a-list-item"),
            pytest.param("```mermaid\nflowchart TD\n    a --> b\n", "flowchart TD\n    a --> b", id="unclosed-runs-to-the-end"),
            pytest.param("```mermaid\n```\n", "", id="empty"),
            pytest.param("```mermaid\r\nflowchart TD\r\n```\r\n", "flowchart TD", id="windows-line-endings"),
        ],
    )
    def test_how_a_block_is_delimited(self, text, expected):
        assert [b.text for b in cli.find_blocks(text, "a.md")] == [expected]

    def test_a_block_after_a_quoted_example_is_still_found(self):
        text = f"````markdown\n{fence(GOOD)}````\n\n{fence(BAD)}"
        assert [(b.line, b.text) for b in cli.find_blocks(text, "a.md")] == [(8, BAD)]


class TestImagePin:
    def test_the_image_is_pinned_to_a_release_tag(self):
        assert re.fullmatch(r"ghcr\.io/mermaid-js/mermaid-cli/mermaid-cli:\d+\.\d+\.\d+", cli.MERMAID_CLI_IMAGE)


class TestRender:
    def test_a_block_that_renders_gives_no_message_and_runs_the_pinned_image_isolated(self):
        runner = docker()
        assert cli.render(cli.Block("a.md", 1, GOOD), runner) is None
        runner.assert_called_once_with(
            [
                "docker",
                "run",
                "--rm",
                "-i",
                "--network",
                "none",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                cli.MERMAID_CLI_IMAGE,
                "-i",
                "-",
                "-o",
                "/tmp/diagram.svg",
            ],
            input=GOOD,
            capture_output=True,
            text=True,
            timeout=cli.BLOCK_TIMEOUT,
            check=False,
        )

    def test_the_message_is_the_renderers_error_without_its_stack(self):
        runner = docker({BAD: completed(1, "Generating single mermaid chart\n", PARSE_ERROR_STDERR)})
        assert cli.render(cli.Block("a.md", 1, BAD), runner) == PARSE_ERROR_MESSAGE

    @pytest.mark.parametrize(
        ("stdout", "stderr", "expected"),
        [
            pytest.param(
                "",
                "Error: Failed to launch the browser process!\n    at ChildProcess.onClose (file:///x.js:1:1)\n",
                "Failed to launch the browser process!",
                id="error-line-alone",
            ),
            pytest.param("", UNKNOWN_DIAGRAM_STDERR, UNKNOWN_DIAGRAM_MESSAGE, id="error-class-other-than-plain-error"),
            pytest.param("", "Error: first\nsecond\n\nthird after a blank line\n", "first\nsecond", id="message-ends-at-a-blank-line"),
            pytest.param("", "warning\nsomething broke\n", "warning\nsomething broke", id="no-error-line-uses-the-stderr-tail"),
            pytest.param("only on stdout\n", "", "only on stdout", id="no-stderr-uses-stdout"),
            pytest.param("", "", "exit status 1", id="no-output-at-all"),
            pytest.param(
                "",
                "Error: " + "\n".join(f"line {n}" for n in range(1, 12)) + "\n",
                "\n".join(["line 1", *(f"line {n}" for n in range(2, 7))]),
                id="long-message-is-cut",
            ),
        ],
    )
    def test_the_message_when_the_output_has_another_shape(self, stdout, stderr, expected):
        assert cli.error_message(1, stdout, stderr) == expected

    def test_a_block_that_takes_too_long_gives_a_message(self):
        runner = create_autospec(subprocess.run, side_effect=subprocess.TimeoutExpired("docker", cli.BLOCK_TIMEOUT))
        assert cli.render(cli.Block("a.md", 1, GOOD), runner) == f"did not finish rendering within {cli.BLOCK_TIMEOUT} seconds"

    @pytest.mark.parametrize("status", cli.DOCKER_FAILED)
    def test_a_docker_failure_is_not_a_verdict_on_the_block(self, status):
        runner = create_autospec(subprocess.run, return_value=completed(status, "", "Cannot connect to the Docker daemon"))
        with pytest.raises(cli.DockerError, match=rf"exit status {status}.*Cannot connect to the Docker daemon"):
            cli.render(cli.Block("a.md", 1, GOOD), runner)

    def test_docker_missing_is_not_a_verdict_on_the_block(self):
        runner = create_autospec(subprocess.run, side_effect=FileNotFoundError(2, "No such file or directory: 'docker'"))
        with pytest.raises(cli.DockerError, match="cannot run docker"):
            cli.render(cli.Block("a.md", 1, GOOD), runner)


class TestTrackedMarkdown:
    def test_only_tracked_markdown_at_any_depth(self, root):
        repo = GitRepo(root, cli)
        repo.git("init", "-q")
        repo.write("README.md", "x")
        repo.write("docs/deep/er/a.md", "x")
        repo.write("docs/notes.txt", "x")
        repo.commit("base")
        repo.write("docs/untracked.md", "x")
        assert sorted(cli.tracked_markdown(root)) == ["README.md", "docs/deep/er/a.md"]


class TestMain:
    def write(self, root: Path, rel: str, *bodies: str) -> None:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Doc\n\n" + "\ntext\n\n".join(fence(body) for body in bodies), encoding="utf-8")

    def test_no_block_means_no_docker_call(self, root, capsys):
        self.write(root, "a.md")
        runner = docker()
        assert cli.main(["a.md", "--root", str(root)], runner) == 0
        runner.assert_not_called()
        assert "No Mermaid blocks" in capsys.readouterr().out

    def test_every_block_renders_after_one_pull(self, root, capsys):
        self.write(root, "a.md", GOOD, GOOD + "\n    b --> c")
        runner = docker()
        assert cli.main(["a.md", "--root", str(root)], runner) == 0
        assert runner.call_args_list[0].args[0] == ["docker", "pull", "--quiet", cli.MERMAID_CLI_IMAGE]
        assert run_inputs(runner) == [GOOD, GOOD + "\n    b --> c"]
        assert "All 2 Mermaid blocks render." in capsys.readouterr().out

    def test_every_failing_block_is_reported_with_its_file_and_line(self, root, capsys):
        self.write(root, "docs/a.md", GOOD, BAD)
        self.write(root, "docs/b.md", BAD)
        runner = docker({BAD: completed(1, "", PARSE_ERROR_STDERR)})
        assert cli.main(["docs/a.md", "docs/b.md", "--root", str(root)], runner) == 1
        out, err = capsys.readouterr()
        assert "::error file=docs/a.md,line=10::docs/a.md:10: Parse error on line 3:" in out
        assert "::error file=docs/b.md,line=3::docs/b.md:3: Parse error on line 3:" in out
        assert "  ----------------------^" in out
        assert "Parser.parseError" not in out
        assert "2 of 3 Mermaid blocks do not render." in err

    def test_a_failed_pull_gives_no_verdict_and_runs_no_block(self, root, capsys):
        self.write(root, "a.md", GOOD)
        runner = docker(pull_result=completed(1, "", "Error response from daemon: denied\n"))
        assert cli.main(["a.md", "--root", str(root)], runner) == 2
        assert run_inputs(runner) == []
        out = capsys.readouterr().out
        assert out.startswith("::error::cannot pull ")
        assert "denied" in out

    def test_a_docker_failure_on_a_block_gives_no_verdict(self, root, capsys):
        self.write(root, "a.md", GOOD)
        runner = docker({GOOD: completed(125, "", "docker: Error response from daemon")})
        assert cli.main(["a.md", "--root", str(root)], runner) == 2
        assert "::error::docker could not run" in capsys.readouterr().out

    def test_only_the_named_files_are_checked(self, root):
        self.write(root, "a.md", GOOD)
        self.write(root, "b.md", BAD)
        runner = docker()
        assert cli.main(["a.md", "--root", str(root)], runner) == 0
        assert run_inputs(runner) == [GOOD]

    def test_without_files_every_tracked_markdown_file_is_checked(self, root):
        repo = GitRepo(root, cli)
        repo.git("init", "-q")
        self.write(root, "docs/a.md", GOOD)
        self.write(root, "README.md", BAD)
        repo.commit("base")
        self.write(root, "docs/untracked.md", "flowchart LR\n    x --> y")
        runner = docker()
        assert cli.main(["--root", str(root)], runner) == 0
        assert sorted(run_inputs(runner)) == sorted([GOOD, BAD])
