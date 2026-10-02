"""Real paramiko objects for tests whose code under test runs a remote command.

The client is a real `paramiko.SSHClient` and the streams `exec_command`
returns are real `ChannelStdinFile`, `ChannelFile` and `ChannelStderrFile`
objects over a real `Channel`, so a test reads the attributes the library
has (`stdout.channel`) and sees a call the real signature would reject
fail. Everything that would touch the network or a file (connect,
exec_command, close, reading known_hosts, reading and writing a stream,
waiting on the exit status) is an autospec'd stand-in; a test sets
`.return_value` on the one the code is expected to call.
"""

from __future__ import annotations

from unittest.mock import create_autospec

import paramiko

_CLIENT_METHODS = ("load_system_host_keys", "load_host_keys", "connect", "exec_command", "invoke_shell", "open_sftp", "close")


def _stub(obj: object, name: str, **kwargs: object) -> None:
    setattr(obj, name, create_autospec(getattr(obj, name), **kwargs))


def stubbed_ssh_client() -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    for name in _CLIENT_METHODS:
        _stub(client, name)
    return client


def _streams(channel: paramiko.Channel, stdout: bytes, stderr: bytes) -> tuple[paramiko.ChannelStdinFile, paramiko.ChannelFile, paramiko.ChannelStderrFile]:
    stdin_stream, stdout_stream, stderr_stream = paramiko.ChannelStdinFile(channel), paramiko.ChannelFile(channel), paramiko.ChannelStderrFile(channel)
    _stub(stdin_stream, "write")
    _stub(stdin_stream, "flush")
    _stub(stdout_stream, "read", return_value=stdout)
    _stub(stderr_stream, "read", return_value=stderr)
    return stdin_stream, stdout_stream, stderr_stream


def exec_result(stdout: bytes = b"", stderr: bytes = b"", exit_status: int = 0):
    """What `exec_command` returns for a command that runs to completion."""
    channel = paramiko.Channel(1)
    _stub(channel, "recv_exit_status", return_value=exit_status)
    return _streams(channel, stdout, stderr)


def pty_result(exit_status: int = 0):
    """What `exec_command(get_pty=True)` returns when the channel never has data ready and has already exited."""
    channel = paramiko.Channel(1)
    _stub(channel, "recv_ready", return_value=False)
    _stub(channel, "exit_status_ready", return_value=True)
    _stub(channel, "recv_exit_status", return_value=exit_status)
    _stub(channel, "recv")
    return _streams(channel, b"", b"")
