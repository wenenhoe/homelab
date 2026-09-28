"""Tests for the bash scripts detect-changes and the boot-test workflow run.

Each script runs for real against a throwaway git repo (the detect
scripts) or with a stub `docker` on PATH (shadow-tag-local-image.sh), so
what's asserted is the script's actual output and the docker commands it
issues, not a re-implementation of its logic. Needs `jq`, which the
detect scripts call and CI's runners ship.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCRIPTS = REPO_ROOT / ".github/scripts"

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


class ScratchRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()

    def write(self, rel: str, text: str = "x\n") -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def git(self, *args: str) -> str:
        env = {**os.environ, **GIT_ENV}
        return subprocess.run(["git", *args], cwd=self.root, env=env, capture_output=True, text=True, check=True).stdout.strip()

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")


@unittest.skipUnless(shutil.which("jq"), "the detect scripts need jq")
class DetectScriptTests(ScratchRepo):
    """detect-changed-compose-apps.sh and detect-changed-dockerfiles.sh."""

    def setUp(self):
        super().setUp()
        self.git("init", "-q")
        self.write(".github/compose-boot-test-exclusions.txt", "# excluded\ncaddy\n")
        for app in ("lldap", "wastebin", "caddy", "dashy", "plain"):
            self.write(f"docker/{app}/compose.yaml{'.j2' if app == 'lldap' else ''}")
        self.write("docker/lldap/configs/env.j2")
        self.write("docker/lldap/scripts/run.sh")
        self.write("docker/wastebin/Dockerfile")
        self.write("docker/caddy/Dockerfile")
        self.write("docker/caddy/configs/env.j2")
        self.write("docker/dashy/configs/conf.yaml.j2")
        self.write("docker/openbao/policies/controller.hcl")
        self.write("docker/molecule-dind/Dockerfile")
        self.write("docs/ci.md")
        self.base = self.commit("base")

    def run_script(self, script: str, key: str) -> list[str]:
        head = self.commit("change")
        out = self.root / "out.txt"
        env = {**os.environ, "GITHUB_OUTPUT": str(out)}
        result = subprocess.run(["bash", str(SCRIPTS / script), self.base, head], cwd=self.root, env=env, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        line = out.read_text().strip()
        self.assertTrue(line.startswith(f"{key}="), line)
        return json.loads(line.removeprefix(f"{key}="))

    def apps(self) -> list[str]:
        return self.run_script("detect-changed-compose-apps.sh", "apps")

    def dockerfiles(self) -> list[str]:
        return self.run_script("detect-changed-dockerfiles.sh", "dockerfiles")

    def test_compose_apps_configs_change(self):
        self.write("docker/lldap/configs/env.j2", "changed\n")
        self.assertEqual(self.apps(), ["lldap"])

    def test_compose_apps_scripts_change(self):
        self.write("docker/lldap/scripts/run.sh", "changed\n")
        self.assertEqual(self.apps(), ["lldap"])

    def test_compose_apps_templated_compose_change(self):
        self.write("docker/lldap/compose.yaml.j2", "changed\n")
        self.assertEqual(self.apps(), ["lldap"])

    def test_compose_apps_dockerfile_change_queues_the_app(self):
        self.write("docker/wastebin/Dockerfile", "changed\n")
        self.assertEqual(self.apps(), ["wastebin"])

    def test_compose_apps_excluded_app_is_never_queued(self):
        self.write("docker/caddy/configs/env.j2", "changed\n")
        self.write("docker/caddy/Dockerfile", "changed\n")
        self.assertEqual(self.apps(), [])

    def test_compose_apps_directory_without_a_compose_file_is_never_queued(self):
        self.write("docker/molecule-dind/Dockerfile", "changed\n")
        self.write("docker/openbao/configs/x.j2", "new\n")
        self.assertEqual(self.apps(), [])

    def test_compose_apps_files_outside_configs_and_scripts_are_ignored(self):
        self.write("docker/openbao/policies/controller.hcl", "changed\n")
        self.write("docs/ci.md", "changed\n")
        self.assertEqual(self.apps(), [])

    def test_compose_apps_deleting_only_a_config_still_queues_the_app(self):
        (self.root / "docker/lldap/configs/env.j2").unlink()
        self.assertEqual(self.apps(), ["lldap"])

    def test_compose_apps_deleting_the_whole_app_queues_nothing(self):
        shutil.rmtree(self.root / "docker/dashy")
        self.assertEqual(self.apps(), [])

    def test_compose_apps_two_apps_are_sorted(self):
        self.write("docker/lldap/configs/env.j2", "changed\n")
        self.write("docker/dashy/configs/conf.yaml.j2", "changed\n")
        self.assertEqual(self.apps(), ["dashy", "lldap"])

    def test_dockerfiles_change_is_queued_even_for_an_excluded_app(self):
        self.write("docker/caddy/Dockerfile", "changed\n")
        self.write("docker/molecule-dind/Dockerfile", "changed\n")
        self.assertEqual(self.dockerfiles(), ["caddy", "molecule-dind"])

    def test_dockerfiles_ignores_everything_but_the_dockerfile(self):
        self.write("docker/caddy/compose.yaml", "changed\n")
        self.write("docker/lldap/configs/env.j2", "changed\n")
        self.assertEqual(self.dockerfiles(), [])

    def test_dockerfiles_deleted_dockerfile_is_not_queued(self):
        (self.root / "docker/wastebin/Dockerfile").unlink()
        self.assertEqual(self.dockerfiles(), [])


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
