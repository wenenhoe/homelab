from __future__ import annotations

import socket
from pathlib import Path

from scratch_run.ssh import PERSIST, Master


class FakeNode:
    """A node's ssh master: `-O check` answers 0 only while it is up, and the interactive login brings it up if it is let in."""

    def __init__(self, up: bool = False, lets_in: bool = True, listens: bool = True) -> None:
        self.up, self.lets_in, self.listens = up, lets_in, listens
        self.commands: list[list[str]] = []

    def run(self, argv, *, env=None, cwd=None, timeout=0):
        self.commands.append(list(argv))
        if "check" in argv:
            return (0, "Master running") if self.up else (255, "Control socket connect: No such file or directory")
        if "exit" in argv:
            was, self.up = self.up, False
            return (0, "Exit request sent.") if was else (255, "")
        raise AssertionError(argv)

    def interactive(self, argv) -> int:
        self.commands.append(list(argv))
        self.up = self.lets_in and self.listens
        return 0 if self.lets_in else 255


def master(node: FakeNode, tmp_path: Path) -> Master:
    return Master("root@pve", tmp_path / "run" / "ssh.sock", node.run, node.interactive)


def test_a_master_that_is_up_is_left_alone(tmp_path):
    node = FakeNode(up=True)
    assert master(node, tmp_path).ensure() is None
    assert len(node.commands) == 1 and "check" in node.commands[0]


def test_a_master_that_is_down_is_opened_with_a_login_and_kept_for_an_hour(tmp_path):
    node = FakeNode()
    assert master(node, tmp_path).ensure() is None
    opened = node.commands[1]
    assert opened[:2] == ["ssh", "-o"] and {"-M", "-N", "-f", f"ControlPersist={PERSIST}"} <= set(opened)
    assert f"ControlPath={tmp_path / 'run' / 'ssh.sock'}" in opened and opened[-1] == "root@pve"
    assert "BatchMode=yes" not in opened  # a prompt has to be possible
    assert (tmp_path / "run").stat().st_mode & 0o077 == 0


def test_a_login_that_fails_says_so_and_how_to_try_it_by_hand(tmp_path):
    problem = master(FakeNode(lets_in=False), tmp_path).ensure()
    assert "ssh to root@pve failed (exit 255)" in problem and "ssh root@pve" in problem


def test_a_login_that_leaves_no_master_listening_is_named(tmp_path):
    problem = master(FakeNode(listens=False), tmp_path).ensure()
    assert "no master is listening at" in problem


def test_the_socket_a_dead_master_left_behind_is_removed_before_a_new_one_is_opened(tmp_path):
    (tmp_path / "run").mkdir()
    stale = tmp_path / "run" / "ssh.sock"
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(stale))
    assert stale.is_socket()
    node = FakeNode()
    seen = []
    original = node.interactive
    node.interactive = lambda argv: (seen.append(stale.exists()), original(argv))[1]
    assert master(node, tmp_path).ensure() is None
    assert seen == [False]


def test_a_file_that_is_not_a_socket_is_not_removed(tmp_path):
    (tmp_path / "run").mkdir()
    keep = tmp_path / "run" / "ssh.sock"
    keep.write_text("mine")
    master(FakeNode(), tmp_path).ensure()
    assert keep.read_text() == "mine"


def test_close_reports_whether_a_master_was_open(tmp_path):
    node = FakeNode(up=True)
    assert master(node, tmp_path).close() is True
    assert master(node, tmp_path).close() is False


def test_is_up_follows_the_masters_answer(tmp_path):
    assert master(FakeNode(up=True), tmp_path).is_up() is True
    assert master(FakeNode(up=False), tmp_path).is_up() is False


def test_a_home_relative_socket_is_expanded():
    assert not str(Master("n", Path("~/x/ssh.sock")).socket).startswith("~")
