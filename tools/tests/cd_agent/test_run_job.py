"""Tests for cd_agent/run_job.py against real git repositories and a real subprocess.

Run via `uv run pytest tools/tests/cd_agent/ -v`.
"""

from __future__ import annotations

import fcntl
import subprocess
import sys
from pathlib import Path

import pytest
from _origin import Origin
from cd_agent import run_job
from cd_agent.run_job import DEPLOYED_FILE, LOCK_FILE, REPO_DIR, Job, JobError, Outcome


def make_job(origin: Origin, state_dir: Path, *command: str, **overrides) -> Job:
    return Job(repo_url=origin.url, state_dir=state_dir, command=command or (sys.executable, "job.py"), **overrides)


def runs(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


class TestParseRepoUrl:
    def test_accepts_an_anonymous_https_url(self):
        assert run_job.parse_repo_url("https://github.com/wenenhoe/homelab.git") == "https://github.com/wenenhoe/homelab.git"

    @pytest.mark.parametrize(
        ("url", "message"),
        [
            pytest.param("http://github.com/wenenhoe/homelab.git", "must use https", id="plain-http"),
            pytest.param("ssh://git@github.com/wenenhoe/homelab.git", "must use https", id="ssh"),
            pytest.param("git@github.com:wenenhoe/homelab.git", "must use https", id="scp-style"),
            pytest.param("file:///srv/homelab.git", "must use https", id="file"),
            pytest.param("/srv/homelab.git", "must use https", id="local-path"),
            pytest.param("https://token@github.com/wenenhoe/homelab.git", "credentials", id="token-in-url"),
            pytest.param("https://user:secret@github.com/wenenhoe/homelab.git", "credentials", id="user-and-password-in-url"),
        ],
    )
    def test_rejects_anything_else(self, url, message):
        with pytest.raises(JobError, match=message):
            run_job.parse_repo_url(url)


class TestActsOnOriginMainOnly:
    def test_runs_main_and_fetches_no_other_ref(self, origin, state_dir, log):
        main = origin.commit("on-main")
        feature = origin.commit("on-feature", branch="feature")
        origin.git("update-ref", "refs/pull/1/head", feature)

        assert run_job.run_job(make_job(origin, state_dir)) is Outcome.RAN

        repo = state_dir / REPO_DIR
        assert runs(log) == ["payload=on-main stray=False cwd=tree"]
        assert subprocess.run(
            ["git", "--git-dir", str(repo), "for-each-ref", "--format=%(refname) %(objectname)"], capture_output=True, text=True, check=True
        ).stdout.splitlines() == [f"refs/remotes/origin/main {main}"]
        assert subprocess.run(["git", "--git-dir", str(repo), "cat-file", "-e", feature], check=False).returncode != 0

    def test_checks_out_exactly_the_commit_it_fetched(self, origin, state_dir, log):
        origin.commit("first")
        second = origin.commit("second")

        run_job.run_job(make_job(origin, state_dir))

        head = subprocess.run(["git", "-C", str(state_dir / "tree"), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        assert (head, runs(log)) == (second, ["payload=second stray=False cwd=tree"])

    def test_follows_main_when_it_moves(self, origin, state_dir, log):
        origin.commit("first")
        run_job.run_job(make_job(origin, state_dir))
        origin.commit("second")

        run_job.run_job(make_job(origin, state_dir))

        assert runs(log) == ["payload=first stray=False cwd=tree", "payload=second stray=False cwd=tree"]

    def test_follows_main_when_it_is_rewound(self, origin, state_dir, log):
        first = origin.commit("first")
        origin.commit("second")
        run_job.run_job(make_job(origin, state_dir))
        origin.git("reset", "-q", "--hard", first)

        run_job.run_job(make_job(origin, state_dir))

        assert runs(log)[-1] == "payload=first stray=False cwd=tree"

    def test_fails_when_origin_has_no_main(self, origin, state_dir, log):
        origin.commit("seed")
        origin.commit("elsewhere", branch="feature")
        origin.git("branch", "-q", "-m", "main", "trunk")

        with pytest.raises(JobError, match="fetch failed"):
            run_job.run_job(make_job(origin, state_dir))

        assert runs(log) == []

    def test_fails_when_origin_is_unreachable(self, origin, state_dir, log):
        job = Job(repo_url="file:///nonexistent/homelab.git", state_dir=state_dir, command=(sys.executable, "job.py"))

        with pytest.raises(JobError, match="fetch failed"):
            run_job.run_job(job)

        assert runs(log) == []

    def test_ignores_the_callers_git_environment(self, origin, state_dir, log, monkeypatch):
        origin.commit("on-main")
        monkeypatch.setenv("GIT_DIR", "/nonexistent")
        monkeypatch.setenv("GIT_WORK_TREE", "/nonexistent")

        assert run_job.run_job(make_job(origin, state_dir)) is Outcome.RAN

        assert runs(log) == ["payload=on-main stray=False cwd=tree"]


class TestCleanTree:
    def test_a_second_run_starts_from_a_clean_tree(self, origin, state_dir, log, monkeypatch):
        origin.commit("pristine")
        monkeypatch.setenv("CD_AGENT_TEST_STRAY", "1")
        run_job.run_job(make_job(origin, state_dir))
        monkeypatch.delenv("CD_AGENT_TEST_STRAY")

        run_job.run_job(make_job(origin, state_dir))

        assert runs(log) == ["payload=pristine stray=False cwd=tree", "payload=pristine stray=False cwd=tree"]

    def test_runs_the_command_from_a_subdirectory_of_the_checkout(self, origin, state_dir, log):
        origin.commit("root", files={"sub/payload.txt": "in-sub\n"})

        outcome = run_job.run_job(make_job(origin, state_dir, sys.executable, "../job.py", cwd="sub"))

        assert (outcome, runs(log)) == (Outcome.RAN, ["payload=in-sub stray=False cwd=sub"])

    @pytest.mark.parametrize(
        ("cwd", "message"),
        [
            pytest.param("..", "leaves the checkout", id="parent"),
            pytest.param("sub/../..", "leaves the checkout", id="parent-via-subdirectory"),
            pytest.param("/etc", "leaves the checkout", id="absolute"),
            pytest.param("escape", "leaves the checkout", id="symlink-out"),
            pytest.param("payload.txt", "not a directory", id="a-file"),
            pytest.param("missing", "not a directory", id="absent"),
        ],
    )
    def test_refuses_a_cwd_outside_the_checkout_or_not_a_directory(self, origin, state_dir, log, cwd, message):
        origin.commit("root", files={"sub/payload.txt": "in-sub\n"})
        (origin.path / "escape").symlink_to("/tmp")
        origin.git("add", "-A")
        origin.git("commit", "-q", "-m", "link")

        with pytest.raises(JobError, match=message):
            run_job.run_job(make_job(origin, state_dir, cwd=cwd))

        assert runs(log) == []


class TestOnChange:
    def test_a_commit_that_succeeded_is_not_run_again(self, origin, state_dir, log):
        commit = origin.commit("only")
        job = make_job(origin, state_dir, on_change=True)

        first = run_job.run_job(job)
        second = run_job.run_job(job)

        assert (first, second, len(runs(log))) == (Outcome.RAN, Outcome.UNCHANGED, 1)
        assert (state_dir / DEPLOYED_FILE).read_text() == commit + "\n"

    def test_a_new_commit_runs_and_replaces_the_record(self, origin, state_dir, log):
        origin.commit("first")
        job = make_job(origin, state_dir, on_change=True)
        run_job.run_job(job)
        second = origin.commit("second")

        outcome = run_job.run_job(job)

        assert (outcome, runs(log)[-1]) == (Outcome.RAN, "payload=second stray=False cwd=tree")
        assert (state_dir / DEPLOYED_FILE).read_text() == second + "\n"

    def test_a_failed_run_records_nothing_and_is_retried(self, origin, state_dir, log, monkeypatch):
        commit = origin.commit("flaky")
        job = make_job(origin, state_dir, on_change=True)
        monkeypatch.setenv("CD_AGENT_TEST_EXIT", "3")

        failed = run_job.run_job(job)

        assert (failed, (state_dir / DEPLOYED_FILE).exists()) == (Outcome.FAILED, False)
        monkeypatch.setenv("CD_AGENT_TEST_EXIT", "0")
        retried = run_job.run_job(job)
        assert (retried, len(runs(log)), (state_dir / DEPLOYED_FILE).read_text()) == (Outcome.RAN, 2, commit + "\n")

    def test_a_failed_new_commit_keeps_the_last_good_record(self, origin, state_dir, log, monkeypatch):
        good = origin.commit("good")
        job = make_job(origin, state_dir, on_change=True)
        run_job.run_job(job)
        origin.commit("bad")
        monkeypatch.setenv("CD_AGENT_TEST_EXIT", "1")

        failed = run_job.run_job(job)
        retried = run_job.run_job(job)

        assert (failed, retried, len(runs(log))) == (Outcome.FAILED, Outcome.FAILED, 3)
        assert (state_dir / DEPLOYED_FILE).read_text() == good + "\n"

    def test_a_command_that_cannot_start_records_nothing(self, origin, state_dir):
        origin.commit("only")

        with pytest.raises(JobError, match="cannot start 'no-such-program-for-cd-agent'"):
            run_job.run_job(make_job(origin, state_dir, "no-such-program-for-cd-agent", on_change=True))

        assert (state_dir / DEPLOYED_FILE).exists() is False

    @pytest.mark.parametrize(
        "content",
        [
            pytest.param("", id="empty"),
            pytest.param("not-a-commit\n", id="not-hex"),
            pytest.param("abc123\n", id="abbreviated"),
            pytest.param("A" * 40 + "\n", id="uppercase"),
        ],
    )
    def test_an_unreadable_record_counts_as_never_deployed(self, origin, state_dir, log, content):
        origin.commit("only")
        state_dir.mkdir(parents=True)
        (state_dir / DEPLOYED_FILE).write_text(content)

        outcome = run_job.run_job(make_job(origin, state_dir, on_change=True))

        assert (outcome, len(runs(log))) == (Outcome.RAN, 1)

    def test_without_on_change_every_run_runs_and_nothing_is_recorded(self, origin, state_dir, log):
        origin.commit("only")
        job = make_job(origin, state_dir)

        outcomes = [run_job.run_job(job), run_job.run_job(job)]

        assert (outcomes, len(runs(log)), (state_dir / DEPLOYED_FILE).exists()) == ([Outcome.RAN, Outcome.RAN], 2, False)


class TestLock:
    def test_a_held_lock_stops_the_run_before_anything_happens(self, origin, state_dir, log):
        origin.commit("only")
        state_dir.mkdir(parents=True)
        with (state_dir / LOCK_FILE).open("a") as holder:
            fcntl.flock(holder, fcntl.LOCK_EX)

            outcome = run_job.run_job(make_job(origin, state_dir))

        assert (outcome, runs(log), (state_dir / REPO_DIR).exists()) == (Outcome.BUSY, [], False)

    def test_the_lock_is_released_when_a_run_ends(self, origin, state_dir, log, monkeypatch):
        origin.commit("only")
        monkeypatch.setenv("CD_AGENT_TEST_EXIT", "1")
        first = run_job.run_job(make_job(origin, state_dir))
        monkeypatch.setenv("CD_AGENT_TEST_EXIT", "0")

        second = run_job.run_job(make_job(origin, state_dir))

        assert (first, second) == (Outcome.FAILED, Outcome.RAN)


class TestMain:
    def test_runs_the_command_after_the_separator(self, origin, state_dir, log):
        origin.commit("via-cli")

        status = run_job.main(["--repo-url", origin.url, "--state-dir", str(state_dir), "--on-change", "--", sys.executable, "job.py"])

        assert (status, runs(log)) == (0, ["payload=via-cli stray=False cwd=tree"])

    def test_an_unchanged_commit_exits_zero_without_running(self, origin, state_dir, log):
        origin.commit("via-cli")
        argv = ["--repo-url", origin.url, "--state-dir", str(state_dir), "--on-change", "--", sys.executable, "job.py"]
        run_job.main(argv)

        status = run_job.main(argv)

        assert (status, len(runs(log))) == (0, 1)

    def test_a_failing_command_exits_one(self, origin, state_dir, log, monkeypatch):
        origin.commit("via-cli")
        monkeypatch.setenv("CD_AGENT_TEST_EXIT", "9")

        status = run_job.main(["--repo-url", origin.url, "--state-dir", str(state_dir), "--", sys.executable, "job.py"])

        assert status == 1

    def test_a_held_lock_exits_with_a_temporary_failure(self, origin, state_dir, log):
        origin.commit("via-cli")
        state_dir.mkdir(parents=True)
        with (state_dir / LOCK_FILE).open("a") as holder:
            fcntl.flock(holder, fcntl.LOCK_EX)

            status = run_job.main(["--repo-url", origin.url, "--state-dir", str(state_dir), "--", sys.executable, "job.py"])

        assert (status, runs(log)) == (75, [])

    def test_a_job_error_exits_one_and_says_why(self, state_dir, capsys):
        status = run_job.main(["--repo-url", "http://github.com/wenenhoe/homelab.git", "--state-dir", str(state_dir), "--", "true"])

        assert (status, "must use https" in capsys.readouterr().err) == (1, True)

    @pytest.mark.parametrize(
        "argv",
        [
            pytest.param(["--repo-url", "https://example.invalid/r.git", "--state-dir", "/tmp/x", "true"], id="no-separator"),
            pytest.param(["--repo-url", "https://example.invalid/r.git", "--state-dir", "/tmp/x", "--"], id="empty-command"),
            pytest.param(["--state-dir", "/tmp/x", "--", "true"], id="no-repo-url"),
            pytest.param(["--repo-url", "https://example.invalid/r.git", "--", "true"], id="no-state-dir"),
        ],
    )
    def test_a_malformed_invocation_is_a_usage_error(self, argv):
        with pytest.raises(SystemExit) as raised:
            run_job.main(argv)

        assert raised.value.code == 2
