"""The command line: the footer's commit and date come from the repository, and a preview serves a build it removes when stopped."""

from __future__ import annotations

import http.server
import signal
import socket
import subprocess
import tempfile
import threading
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest
from doc_site import __main__ as cli
from doc_site import site


@pytest.fixture
def repository(tmp_path, monkeypatch):
    """A one-commit repository the command reads its commit from; yields the commit id."""
    env = {"GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a@example.com", "GIT_COMMITTER_NAME": "a", "GIT_COMMITTER_EMAIL": "a@example.com"}
    env |= {"GIT_COMMITTER_DATE": "2026-11-21T16:12:00+0800", "GIT_AUTHOR_DATE": "2026-11-21T16:12:00+0800", "PATH": "/usr/bin:/bin"}
    run = lambda *args: subprocess.run(["git", "-C", str(tmp_path), *args], env=env, check=True, capture_output=True, text=True).stdout.strip()  # noqa: E731
    run("init", "-q")
    run("commit", "-q", "--allow-empty", "-m", "x")
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    return run("rev-parse", "HEAD")


def test_the_stamp_is_the_commit_and_its_date(repository):
    assert cli.stamp_of(repository) == site.Stamp(repository, "2026-11-21T16:12:00+08:00")


def test_a_commit_the_repository_lacks_is_refused(repository):
    with pytest.raises(SystemExit, match="is not a commit"):
        cli.stamp_of("0" * 40)


@pytest.mark.parametrize("commit", ["main", "HEAD", "abc1234", "--output=x"])
def test_only_a_full_commit_id_is_passed_to_git(commit):
    with pytest.raises(SystemExit, match="full 40-character"):
        cli.stamp_of(commit)


@pytest.fixture
def built():
    """Stands in for the build, which needs a browser; yields the directories written to."""
    directories = []

    def write(out, stamp=None):
        directories.append(out)
        (out / "index.html").write_text("a built page", encoding="utf-8")
        return ["index.html"]

    with patch.object(site, "write", autospec=True, side_effect=write):
        yield directories


@pytest.mark.parametrize(
    "stop",
    [
        pytest.param(signal.SIGINT, id="ctrl-c"),
        pytest.param(signal.SIGTERM, id="sigterm"),
        pytest.param(signal.SIGHUP, id="sighup"),
    ],
)
def test_a_preview_serves_the_build_on_localhost_and_removes_it_when_stopped(built, stop):
    handlers = [signal.getsignal(signum) for signum in cli.STOP_SIGNALS]
    seen = {}

    def serve_one_request(server):
        host, port = server.server_address
        fetch = threading.Thread(target=lambda: seen.update(body=urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10).read()))
        fetch.start()
        server.handle_request()
        fetch.join()
        seen["host"] = host
        signal.raise_signal(stop)

    with patch.object(http.server.ThreadingHTTPServer, "serve_forever", autospec=True, side_effect=serve_one_request):
        assert cli.main(["--serve", "--port", "0"]) == 0
    assert seen == {"body": b"a built page", "host": "127.0.0.1"}
    assert not Path(built[0]).exists()
    assert [signal.getsignal(signum) for signum in cli.STOP_SIGNALS] == handlers


def test_a_second_stop_signal_does_not_cut_the_removal_short(built):
    cleanup = tempfile.TemporaryDirectory.cleanup

    def signalled_cleanup(directory):
        signal.raise_signal(signal.SIGTERM)
        cleanup(directory)

    with (
        patch.object(http.server.ThreadingHTTPServer, "serve_forever", autospec=True, side_effect=lambda server: signal.raise_signal(signal.SIGTERM)),
        patch.object(tempfile.TemporaryDirectory, "cleanup", autospec=True, side_effect=signalled_cleanup),
    ):
        assert cli.main(["--serve", "--port", "0"]) == 0
    assert not Path(built[0]).exists()


def test_a_port_in_use_is_refused_before_the_build(built):
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        with pytest.raises(SystemExit, match="cannot serve on port"):
            cli.main(["--serve", "--port", str(taken.getsockname()[1])])
    assert built == []


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        pytest.param(["--serve", "--out", "x"], "not allowed with argument", id="serve-and-out"),
        pytest.param(["--out", "x", "--port", "1"], "--port goes with --serve", id="port-without-serve"),
        pytest.param([], "one of the arguments", id="neither"),
    ],
)
def test_options_that_do_not_go_together_are_refused(built, capsys, argv, message):
    with pytest.raises(SystemExit):
        cli.main(argv)
    assert message in capsys.readouterr().err
    assert built == []
