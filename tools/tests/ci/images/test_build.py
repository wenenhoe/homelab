"""Tests for ci.images.build, through a stub command runner.

The runner records every command and answers `docker compose config
--images` from a canned listing, so nothing here needs docker.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ci.images import build
from ci.images.registry import ImageError


class StubRunner:
    def __init__(self, images: str = "", codes: dict[str, int] | None = None):
        self.images = images
        self.codes = codes or {}
        self.calls: list[tuple[list[str], Path, bool]] = []

    def __call__(self, args: list[str], cwd: Path, capture: bool = False) -> subprocess.CompletedProcess[str]:
        self.calls.append((args, cwd, capture))
        stdout = self.images if args[:2] == ["docker", "compose"] else ""
        return subprocess.CompletedProcess(args, self.codes.get(args[1] if args[0] == "docker" else args[0], 0), stdout=stdout)

    @property
    def commands(self) -> list[list[str]]:
        return [args for args, _, _ in self.calls]


class Scratch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()

    def write(self, rel: str, text: str = "x\n") -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


class ShadowTagTests(Scratch):
    def setUp(self):
        super().setUp()
        self.write("docker/wastebin/Dockerfile")

    def test_builds_the_context_tagged_as_the_pinned_ref(self):
        runner = StubRunner("ghcr.io/wenenhoe/wastebin:3.7.2\nredis:7\n")
        self.assertEqual(build.shadow_tag(self.root, "wastebin", "/tmp/c/compose.yaml", runner), 0)
        self.assertEqual(
            runner.commands,
            [
                ["docker", "compose", "-f", "/tmp/c/compose.yaml", "config", "--images"],
                ["docker", "build", "--tag", "ghcr.io/wenenhoe/wastebin:3.7.2", "docker/wastebin"],
            ],
        )
        self.assertTrue(all(cwd == self.root for _, cwd, _ in runner.calls))

    def test_the_compose_listing_is_captured_and_the_build_streams(self):
        runner = StubRunner("ghcr.io/wenenhoe/wastebin:3.7.2\n")
        build.shadow_tag(self.root, "wastebin", "c.yaml", runner)
        self.assertEqual([capture for _, _, capture in runner.calls], [True, False])

    def test_the_same_image_listed_twice_is_tagged_once(self):
        runner = StubRunner("ghcr.io/wenenhoe/wastebin:3.7.2\nghcr.io/wenenhoe/wastebin:3.7.2\n")
        build.shadow_tag(self.root, "wastebin", "c.yaml", runner)
        self.assertEqual(runner.commands[1].count("--tag"), 1)

    def test_two_tags_of_the_same_image_are_both_applied(self):
        runner = StubRunner("ghcr.io/wenenhoe/wastebin:3.7.2\nghcr.io/wenenhoe/wastebin:latest\n")
        build.shadow_tag(self.root, "wastebin", "c.yaml", runner)
        self.assertEqual(
            runner.commands[1], ["docker", "build", "--tag", "ghcr.io/wenenhoe/wastebin:3.7.2", "--tag", "ghcr.io/wenenhoe/wastebin:latest", "docker/wastebin"]
        )

    def test_only_this_apps_image_is_shadowed_when_the_compose_file_pins_others(self):
        runner = StubRunner("ghcr.io/wenenhoe/molecule-dind:latest\nghcr.io/wenenhoe/wastebin:3.7.2\n")
        build.shadow_tag(self.root, "wastebin", "c.yaml", runner)
        self.assertEqual(runner.commands[1], ["docker", "build", "--tag", "ghcr.io/wenenhoe/wastebin:3.7.2", "docker/wastebin"])

    def test_the_context_comes_from_the_registry_not_the_app_name(self):
        self.write("docker/caddy/Dockerfile")
        runner = StubRunner("ghcr.io/wenenhoe/caddy-digitalocean:2.11.4\n")
        build.shadow_tag(self.root, "caddy", "c.yaml", runner)
        self.assertEqual(runner.commands[1][-1], "docker/caddy")

    def test_app_without_a_dockerfile_builds_nothing(self):
        runner = StubRunner("ghcr.io/wenenhoe/other:1\n")
        self.assertEqual(build.shadow_tag(self.root, "other", "c.yaml", runner), 0)
        self.assertEqual(runner.calls, [])

    def test_compose_file_pinning_none_of_its_image_builds_nothing(self):
        runner = StubRunner("redis:7\nghcr.io/wenenhoe/molecule-dind:latest\n")
        self.assertEqual(build.shadow_tag(self.root, "wastebin", "c.yaml", runner), 0)
        self.assertEqual(len(runner.calls), 1)

    def test_a_dockerfile_with_no_registry_entry_is_an_error(self):
        self.write("docker/newapp/Dockerfile")
        with self.assertRaisesRegex(ImageError, "no image entry for 'newapp'"):
            build.shadow_tag(self.root, "newapp", "c.yaml", StubRunner())

    def test_a_failing_compose_listing_stops_before_building(self):
        runner = StubRunner(codes={"compose": 3})
        self.assertEqual(build.shadow_tag(self.root, "wastebin", "c.yaml", runner), 3)
        self.assertEqual(len(runner.calls), 1)

    def test_a_failing_build_returns_its_code(self):
        runner = StubRunner("ghcr.io/wenenhoe/wastebin:3.7.2\n", codes={"build": 1})
        self.assertEqual(build.shadow_tag(self.root, "wastebin", "c.yaml", runner), 1)


class BuildCheckTests(Scratch):
    def setUp(self):
        super().setUp()
        self.write("docker/wastebin/Dockerfile")

    def test_missing_smoke_test_fails_before_building(self):
        runner = StubRunner()
        self.assertEqual(build.build_check(self.root, "wastebin", runner), 1)
        self.assertEqual(runner.calls, [])

    def test_builds_then_runs_the_smoke_test_with_the_local_ref(self):
        self.write(".github/image-smoke-tests/wastebin.sh")
        runner = StubRunner()
        self.assertEqual(build.build_check(self.root, "wastebin", runner), 0)
        self.assertEqual(
            runner.commands,
            [
                ["docker", "build", "--tag", "local/wastebin:pr-check", "docker/wastebin"],
                ["bash", ".github/image-smoke-tests/wastebin.sh", "local/wastebin:pr-check"],
            ],
        )
        self.assertTrue(all(cwd == self.root and not capture for _, cwd, capture in runner.calls))

    def test_a_failed_build_skips_the_smoke_test(self):
        self.write(".github/image-smoke-tests/wastebin.sh")
        runner = StubRunner(codes={"build": 1})
        self.assertEqual(build.build_check(self.root, "wastebin", runner), 1)
        self.assertEqual(len(runner.calls), 1)

    def test_a_failing_smoke_test_fails_the_check(self):
        self.write(".github/image-smoke-tests/wastebin.sh")
        runner = StubRunner(codes={"bash": 7})
        self.assertEqual(build.build_check(self.root, "wastebin", runner), 7)


class RepoInvariantTests(unittest.TestCase):
    def test_every_dockerfile_has_a_smoke_test_and_a_registry_entry(self):
        from ci.images.registry import IMAGES

        for dockerfile in sorted((build.REPO_ROOT / "docker").glob("*/Dockerfile")):
            app = dockerfile.parent.name
            with self.subTest(app=app):
                self.assertTrue((build.REPO_ROOT / build.SMOKE_DIR / f"{app}.sh").is_file())
                self.assertIn(app, IMAGES)

    def test_every_smoke_test_has_a_dockerfile(self):
        for smoke in sorted((build.REPO_ROOT / build.SMOKE_DIR).glob("*.sh")):
            with self.subTest(app=smoke.stem):
                self.assertTrue((build.REPO_ROOT / f"docker/{smoke.stem}/Dockerfile").is_file())


if __name__ == "__main__":
    unittest.main()
