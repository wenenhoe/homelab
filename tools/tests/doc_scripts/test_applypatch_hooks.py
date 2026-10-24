"""The `git am` hooks run against real `git am` in a throwaway repository.

`pre-commit` is a stub: `pre-commit run generate-doc-indexes` rebuilds a one-line-per-project
`docs/projects/README.md`, and the installed commit hook fails when that file is stale. That is
enough to show which hook puts the regenerated view into the commit. Both stubs also do what
pre-commit does with unstaged changes: stash them, run, and put them back over whatever the run
wrote, rolling the run's output back when they no longer apply.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
VIEWS = ("docs/projects/README.md", "docs/project-planning.md", "docs/decisions/README.md")

LISTING = """#!/usr/bin/env bash
# Prints what docs/projects/README.md should hold for the projects in the working tree.
echo "# Index"
for f in docs/projects/*.md; do
  [ "$(basename "$f")" = README.md ] || basename "$f"
done
"""
STASH = """# Runs "$@" with the working tree's unstaged changes set aside, as pre-commit does.
with_unstaged_stashed() {
  local patch status=0
  patch="$(mktemp)"
  git diff --binary > "$patch"
  [ ! -s "$patch" ] || git checkout -- .
  "$@" || status=$?
  if [ -s "$patch" ]; then
    git apply "$patch" 2>/dev/null || { git checkout -- .; git apply "$patch"; }
  fi
  rm -f "$patch"
  return "$status"
}
"""
STUB_PRE_COMMIT = """#!/usr/bin/env bash
here="$(dirname "$0")"
. "$here/stash"
regenerate() { "$here/listing" > docs/projects/README.md; }
if [ "$1" = run ] && [ "$2" = generate-doc-indexes ]; then
  with_unstaged_stashed regenerate
fi
"""
COMMIT_HOOK = """#!/usr/bin/env bash
# Fails when the staged README does not list the projects in the index.
cd "$(git rev-parse --show-toplevel)"
. "$STASH"
check() { diff <(git show :docs/projects/README.md) <("$LISTING") >/dev/null || { echo "stale view" >&2; return 1; }; }
with_unstaged_stashed check
"""
PRE_APPLYPATCH_WITHOUT_STAGING = """#!/usr/bin/env bash
set -euo pipefail
hook="$(git rev-parse --git-path hooks)/pre-commit"
pre-commit run generate-doc-indexes >/dev/null 2>&1 || true
git add -- docs/projects/README.md docs/project-planning.md docs/decisions/README.md
exec "$hook"
"""


def git(cwd: Path, *args: str, check: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    cmd = ["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t.t", "-c", "commit.gpgsign=false", *args]
    return subprocess.run(cmd, check=check, capture_output=True, text=True, env={**os.environ, "LC_ALL": "C", **(env or {})})


class Sandbox:
    def __init__(self, base: Path) -> None:
        self.bin = base / "bin"
        self.hooks = base / "hooks"
        self.repo = base / "repo"
        self.patches = base / "patches"
        for d in (self.bin, self.hooks, self.repo, self.patches):
            d.mkdir()
        (self.bin / "listing").write_text(LISTING)
        (self.bin / "stash").write_text(STASH)
        (self.bin / "pre-commit").write_text(STUB_PRE_COMMIT)
        (self.hooks / "pre-commit").write_text(COMMIT_HOOK.replace("$LISTING", str(self.bin / "listing")).replace("$STASH", str(self.bin / "stash")))
        for script in (self.bin / "listing", self.bin / "pre-commit", self.hooks / "pre-commit"):
            script.chmod(0o755)
        git(self.repo, "init", "-q", "-b", "main")
        self.write("docs/projects/README.md", "# Index\n")
        self.write("docs/project-planning.md", "# Planning\n")
        self.write("docs/decisions/README.md", "# Decisions\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        self.base = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        git(self.repo, "config", "core.hooksPath", str(self.hooks))

    def write(self, rel: str, text: str) -> None:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def install(self, *names: str) -> None:
        for name in names:
            shutil.copy(REPO / ".githooks" / name, self.hooks / name)

    def project_patch(self, name: str) -> Path:
        """A patch adding one project and leaving the generated views alone."""
        git(self.repo, "checkout", "-q", "-b", name, self.base)
        self.write(f"docs/projects/{name}.md", f"{name}\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "--no-verify", "-m", f"docs: add {name}")
        out = git(self.repo, "format-patch", "-1", "-o", str(self.patches)).stdout.strip()
        git(self.repo, "checkout", "-q", "main")
        return Path(out)

    def am(self, *patches: Path) -> subprocess.CompletedProcess[str]:
        env = {"PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}"}
        return git(self.repo, "am", *map(str, patches), check=False, env=env)

    def committed(self, rel: str) -> str:
        return git(self.repo, "show", f"HEAD:{rel}").stdout

    def count(self) -> int:
        return int(git(self.repo, "rev-list", "--count", "HEAD").stdout)


@pytest.fixture
def sandbox(root: Path) -> Sandbox:
    return Sandbox(root)


class TestApplypatchHooks:
    def test_views_regenerated_by_the_hooks_land_in_the_commit(self, sandbox: Sandbox) -> None:
        sandbox.install("pre-applypatch", "post-applypatch")
        result = sandbox.am(sandbox.project_patch("alpha"))
        assert result.returncode == 0, result.stderr
        assert sandbox.committed("docs/projects/README.md") == "# Index\nalpha.md\n"
        assert git(sandbox.repo, "status", "--porcelain").stdout == ""

    def test_series_from_separate_threads_applies_without_a_view_conflict(self, sandbox: Sandbox) -> None:
        sandbox.install("pre-applypatch", "post-applypatch")
        patches = [sandbox.project_patch("alpha"), sandbox.project_patch("beta")]
        result = sandbox.am(*patches)
        assert result.returncode == 0, result.stderr
        assert sandbox.count() == 3
        assert sandbox.committed("docs/projects/README.md") == "# Index\nalpha.md\nbeta.md\n"
        assert git(sandbox.repo, "show", "-s", "--format=%an|%s", "HEAD").stdout.strip() == "t|docs: add beta"

    def test_amend_keeps_the_patch_author_and_date(self, sandbox: Sandbox) -> None:
        sandbox.install("pre-applypatch", "post-applypatch")
        patch = sandbox.project_patch("alpha")
        before = git(sandbox.repo, "show", "-s", "--format=%an <%ae> %aI", "alpha").stdout
        sandbox.am(patch)
        assert git(sandbox.repo, "show", "-s", "--format=%an <%ae> %aI", "HEAD").stdout == before

    def test_a_failing_commit_hook_stops_the_apply_and_makes_no_commit(self, sandbox: Sandbox) -> None:
        sandbox.install("pre-applypatch", "post-applypatch")
        (sandbox.hooks / "pre-commit").write_text("#!/usr/bin/env bash\necho nope >&2\nexit 1\n")
        result = sandbox.am(sandbox.project_patch("alpha"))
        assert result.returncode != 0
        assert sandbox.count() == 1

    @pytest.mark.parametrize(
        ("installed", "view_committed"),
        [
            pytest.param((), False, id="no-hooks-the-commit-hook-never-runs"),
            pytest.param(("pre-applypatch",), False, id="pre-only-the-view-stays-out-of-the-commit"),
        ],
    )
    def test_controls_the_view_is_missing_without_both_hooks(self, sandbox: Sandbox, installed: tuple[str, ...], view_committed: bool) -> None:
        sandbox.install(*installed)
        sandbox.am(sandbox.project_patch("alpha"))
        assert (sandbox.committed("docs/projects/README.md") == "# Index\nalpha.md\n") is view_committed

    def test_control_without_staging_the_views_first_the_second_patch_of_a_series_stops(self, sandbox: Sandbox) -> None:
        sandbox.install("post-applypatch")
        (sandbox.hooks / "pre-applypatch").write_text(PRE_APPLYPATCH_WITHOUT_STAGING)
        (sandbox.hooks / "pre-applypatch").chmod(0o755)
        result = sandbox.am(sandbox.project_patch("alpha"), sandbox.project_patch("beta"))
        assert result.returncode != 0
        assert "stale view" in result.stderr
        assert sandbox.count() == 2

    def test_missing_pre_commit_hook_is_reported(self, sandbox: Sandbox) -> None:
        sandbox.install("pre-applypatch")
        (sandbox.hooks / "pre-commit").unlink()
        result = sandbox.am(sandbox.project_patch("alpha"))
        assert result.returncode != 0
        assert "pre-commit hook is not installed" in result.stderr


def test_views_named_by_the_hooks_exist_in_the_repo() -> None:
    for hook in ("pre-applypatch", "post-applypatch"):
        text = (REPO / ".githooks" / hook).read_text()
        assert all(view in text for view in VIEWS), hook
        assert all((REPO / view).is_file() for view in VIEWS)
