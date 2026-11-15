"""Stand-ins the scratch_run tests share: a backend with behaviour of its own, a runner that records its commands and a master connection.

They live here and not in conftest.py because a test imports them by name, and `conftest` is the same module name in every test directory."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from scratch_run.spec import Spec

RUNS = Path(__file__).resolve().parents[3] / "tofu" / "scratch" / "opnsense" / "runs"


@dataclass
class FakeBackend:
    """Answers each call from `answers` (keyed by call name, or by `kind:id`) and records the calls it got."""

    answers: dict[str, tuple[int, str]] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    secret_values: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    blocked: bool = False  # a block rule is present: the DNS flow it breaks fails, as on a gateway

    def _answer(self, name: str) -> tuple[int, str]:
        self.calls.append(name)
        return self.answers.get(name, (0, f"{name} output\n"))

    def preflight(self, spec: Spec) -> list[str]:
        self.calls.append("preflight")
        return self.problems

    def up(self, spec: Spec) -> tuple[int, str]:
        return self._answer("up")

    def play(self, spec: Spec, mode: str) -> tuple[int, str]:
        status, output = self._answer(f"play:{mode}")
        return status, output if mode == "apply" else "localhost : ok=3 changed=0 failed=0\n"

    def flows(self, tags: tuple[str, ...], ids: tuple[str, ...]) -> tuple[int, str]:
        status, output = self._answer("flows:" + ",".join((*tags, *ids)))
        return (
            (1, "FAIL services-gateway-dns: blocked: TimeoutError: timed out\n")
            if self.blocked and "services-gateway-dns" in ids and status == 0
            else (status, output)
        )

    def block(self, spec: Spec, state: str) -> tuple[int, str]:
        self.blocked = state == "present"
        return self._answer(f"block:{state}")

    def down(self) -> tuple[int, str]:
        return self._answer("down")

    def secrets(self) -> list[str]:
        return self.secret_values


@dataclass
class RecordingRunner:
    """A `scratch_run.node.Runner` that records each command and answers 0 unless a rule says otherwise."""

    rules: dict[str, tuple[int, str]] = field(default_factory=dict)  # a word in the command line -> its answer
    calls: list[tuple[list[str], dict[str, str] | None, Path | None]] = field(default_factory=list)
    echoed: list[Callable[[str], None] | None] = field(default_factory=list)  # the `on_output` each call got

    def __call__(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
        timeout: int = 0,
        on_output: Callable[[str], None] | None = None,
    ) -> tuple[int, str]:
        self.calls.append((list(argv), dict(env) if env is not None else None, cwd))
        self.echoed.append(on_output)
        line = " ".join(argv)
        for word, answer in self.rules.items():
            if word in line:
                return answer
        return 0, ""

    def lines(self) -> list[str]:
        return [" ".join(argv) for argv, _, _ in self.calls]


class FakeMaster:
    """A `scratch_run.ssh.Master` that records what it was asked and opens or fails as told."""

    def __init__(self, node: str, socket: Path, up: bool = False, problem: str | None = None) -> None:
        self.node, self.socket, self.up, self.problem = node, socket, up, problem
        self.asked: list[str] = []

    def ensure(self) -> str | None:
        self.asked.append("ensure")
        self.up = self.up or self.problem is None
        return None if self.up else self.problem

    def is_up(self) -> bool:
        self.asked.append("is_up")
        return self.up

    def close(self) -> bool:
        self.asked.append("close")
        was, self.up = self.up, False
        return was


def masters(made: list[FakeMaster] | None = None, **options):
    """A `master_factory` for `scratch_run.__main__.main`; the masters it makes are appended to `made`."""

    def make(node: str, socket: Path) -> FakeMaster:
        master = FakeMaster(node, socket, **options)
        if made is not None:
            made.append(master)
        return master

    return make
