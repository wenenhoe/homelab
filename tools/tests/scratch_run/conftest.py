"""Stand-ins the scratch_run tests share: a backend with behaviour of its own and a runner that records its commands."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from scratch_run.spec import Spec, load_spec

RUNS = Path(__file__).resolve().parents[3] / "tofu" / "scratch" / "opnsense" / "runs"


@pytest.fixture
def rehearsal() -> Spec:
    return load_spec(RUNS / "rehearsal.yaml")


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
        return (1, "services-gateway-dns failed\n") if self.blocked and "services-gateway-dns" in ids and status == 0 else (status, output)

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

    def __call__(self, argv: Sequence[str], *, env: Mapping[str, str] | None = None, cwd: Path | None = None, timeout: int = 0) -> tuple[int, str]:
        self.calls.append((list(argv), dict(env) if env is not None else None, cwd))
        line = " ".join(argv)
        for word, answer in self.rules.items():
            if word in line:
                return answer
        return 0, ""

    def lines(self) -> list[str]:
        return [" ".join(argv) for argv, _, _ in self.calls]
