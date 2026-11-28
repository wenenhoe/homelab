"""Everything particular to this repository, in one object: nothing else in the command names its remote, identities, hooks or paths."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Identity:
    name: str
    email: str

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>"


@dataclass(frozen=True)
class Need:
    """What a hook asks of the machine, and the hooks that cannot run without it."""

    name: str
    hooks: tuple[str, ...]


@dataclass(frozen=True)
class Repository:
    remote: str
    default_base: str
    # The environment variable and the value that say this is a session on a machine that is thrown away.
    session_variable: tuple[str, str]
    committer: Identity
    date_offset: str
    trailer_email: str
    other_trailers: tuple[str, ...]
    needs: tuple[Need, ...]
    # A change to one of these is to code that runs the checks, a hook, CI or the agent's own settings.
    tooling_prefixes: tuple[str, ...]
    # The Python the doc tools need, which `pre-commit` is run with when none is installed.
    python: str
    ansible_dir: str
    series_prompt: str
    replay_command: str

    @property
    def land_command(self) -> str:
        return f"{self.replay_command} --land"


# Every hook of the pre-commit configuration whose id ends in `-docker` is listed, which a test holds.
HOMELAB = Repository(
    remote="origin",
    default_base="main",
    session_variable=("CLAUDE_CODE_REMOTE", "true"),
    committer=Identity("Claude", "noreply@anthropic.com"),
    date_offset=" +0800",
    trailer_email="noreply@anthropic.com",
    other_trailers=("Plan-Confirmed", "Editorial-Fix"),
    needs=(
        Need("a Docker daemon", ("dclint-docker", "hadolint-docker", "actionlint-docker")),
        Need("a download of the Go toolchain", ("gitleaks",)),
        Need("the GitHub API", ("zizmor",)),
        Need("the Ansible collections", ("ansible-lint",)),
    ),
    tooling_prefixes=(".githooks/", ".pre-commit-config.yaml", ".config/", ".github/", ".claude/", "tools/"),
    python="3.14",
    ansible_dir="ansible",
    # `landing-a-series.md` gives these two commands; a test holds them equal to its blocks.
    series_prompt="read -r -p 'series file: ' series",
    replay_command='uv run python -m land_series "$series" --repo ..',
)
