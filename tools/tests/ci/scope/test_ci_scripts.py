"""Tests for the bash scripts the boot-test and Dockerfile jobs run.

Each runs for real with a stub `docker` on PATH, so what's asserted is
the docker commands the script issues, not a re-implementation of its
logic.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = REPO_ROOT / ".github/scripts"


class ScratchRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()

    def write(self, rel: str, text: str = "x\n") -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


class ShadowTagTests(ScratchRepo):
    """shadow-tag-local-image.sh against a stub `docker`."""

    STUB = """#!/usr/bin/env bash
if [ "$1" = compose ]; then
  printf '%s' "$FAKE_IMAGES"
  exit 0
fi
printf '%s\\n' "$*" >> "$DOCKER_LOG"
"""

    def setUp(self):
        super().setUp()
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        stub = bin_dir / "docker"
        stub.write_text(self.STUB)
        stub.chmod(0o755)
        self.bin_dir = bin_dir
        self.log = self.root / "docker.log"
        self.write("docker/app/Dockerfile")

    def run_script(
        self,
        app: str,
        images: str = "",
    ) -> subprocess.CompletedProcess:
        env = {**os.environ, "PATH": f"{self.bin_dir}:{os.environ['PATH']}", "FAKE_IMAGES": images, "DOCKER_LOG": str(self.log)}
        return subprocess.run(
            ["bash", str(SCRIPTS / "shadow-tag-local-image.sh"), app, "compose.yaml"], cwd=self.root, env=env, capture_output=True, text=True, check=False
        )

    def builds(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_builds_the_dockerfile_as_the_pinned_image(self):
        result = self.run_script("app", "ghcr.io/wenenhoe/app:1.2.3\nredis:7\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.builds(), ["build --tag ghcr.io/wenenhoe/app:1.2.3 docker/app"])

    def test_the_same_image_listed_twice_is_one_build(self):
        result = self.run_script("app", "ghcr.io/wenenhoe/app:1.2.3\nghcr.io/wenenhoe/app:1.2.3\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.builds()), 1)

    def test_app_without_a_dockerfile_builds_nothing(self):
        result = self.run_script("other", "ghcr.io/wenenhoe/other:1\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.builds(), [])

    def test_no_wenenhoe_image_builds_nothing(self):
        result = self.run_script("app", "redis:7\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.builds(), [])
        self.assertIn("nothing to shadow", result.stdout)

    def test_two_wenenhoe_images_is_an_error(self):
        result = self.run_script("app", "ghcr.io/wenenhoe/app:1\nghcr.io/wenenhoe/side:2\n")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.builds(), [])
        self.assertIn("cannot tell which", result.stdout)


class BuildAndSmokeTests(ScratchRepo):
    """build-and-smoke-test-image.sh against a stub `docker`."""

    def setUp(self):
        super().setUp()
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        stub = bin_dir / "docker"
        stub.write_text('#!/usr/bin/env bash\nprintf \'%s\\n\' "$*" >> "$DOCKER_LOG"\n')
        stub.chmod(0o755)
        self.bin_dir = bin_dir
        self.log = self.root / "docker.log"

    def run_script(self, app: str) -> subprocess.CompletedProcess:
        env = {**os.environ, "PATH": f"{self.bin_dir}:{os.environ['PATH']}", "DOCKER_LOG": str(self.log)}
        return subprocess.run(
            ["bash", str(SCRIPTS / "build-and-smoke-test-image.sh"), app], cwd=self.root, env=env, capture_output=True, text=True, check=False
        )

    def test_missing_smoke_test_fails_before_building(self):
        result = self.run_script("app")
        self.assertEqual(result.returncode, 1)
        self.assertIn("doesn't exist", result.stdout)
        self.assertFalse(self.log.exists())

    def test_builds_then_runs_the_smoke_test_with_the_image_ref(self):
        self.write(".github/image-smoke-tests/app.sh", '#!/usr/bin/env bash\nprintf "smoke %s\\n" "$1" >> "$DOCKER_LOG"\n')
        result = self.run_script("app")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text().splitlines(), ["build --tag local/app:pr-check docker/app", "smoke local/app:pr-check"])

    def test_failing_smoke_test_fails_the_script(self):
        self.write(".github/image-smoke-tests/app.sh", "#!/usr/bin/env bash\nexit 3\n")
        self.assertNotEqual(self.run_script("app").returncode, 0)


class RepoInvariantTests(unittest.TestCase):
    def test_every_dockerfile_has_a_smoke_test(self):
        for dockerfile in sorted((REPO_ROOT / "docker").glob("*/Dockerfile")):
            app = dockerfile.parent.name
            with self.subTest(app=app):
                self.assertTrue((REPO_ROOT / f".github/image-smoke-tests/{app}.sh").is_file())

    def test_every_smoke_test_has_a_dockerfile(self):
        for smoke in sorted((REPO_ROOT / ".github/image-smoke-tests").glob("*.sh")):
            with self.subTest(app=smoke.stem):
                self.assertTrue((REPO_ROOT / f"docker/{smoke.stem}/Dockerfile").is_file())


if __name__ == "__main__":
    unittest.main()
