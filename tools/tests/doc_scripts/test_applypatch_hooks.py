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
import sys
from datetime import date
from pathlib import Path

import pytest
from _doc_fixtures import write_doc
from doc_scripts import generate_doc_indexes as generator

REPO = Path(__file__).resolve().parents[3]
VIEW_LIST = ".githooks/generated-views"
VIEWS = tuple((REPO / VIEW_LIST).read_text().split())

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
        for view in VIEWS:
            if not (self.repo / view).exists():
                self.write(view, "# View\n")
        self.write(VIEW_LIST, "\n".join(VIEWS) + "\n")
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


RENDER = """import sys
from pathlib import Path
{before}
from doc_scripts.generate_doc_indexes import render_explorations_table
print(render_explorations_table(Path.cwd()))
"""
# What last_commit_date did before it dated an uncommitted file: ask git about commits only.
LOG_ONLY = """import subprocess
from datetime import date
from doc_scripts import generate_doc_indexes
def log_only(root, path, today=None):
    cmd = ["git", "-C", str(root), "log", "-1", "--format=%cs", "--", str(path.relative_to(root))]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
    return date.fromisoformat(out) if out else None
generate_doc_indexes.last_commit_date = log_only
"""
PLANNING_PRE_COMMIT = """#!/usr/bin/env bash
here="$(dirname "$0")"
. "$here/stash"
regenerate() { PYTHONPATH="@TOOLS@" "@PYTHON@" "$here/render.py" > docs/project-planning.md; }
if [ "$1" = run ] && [ "$2" = generate-doc-indexes ]; then
  with_unstaged_stashed regenerate
fi
"""


class TestPlanningViewDates:
    """The planning view dates an exploration by the commit that adds it, and the hooks
    regenerate it before that commit exists. Real `git am`, real hooks, the real generator."""

    def planning(self, sandbox: Sandbox, log_only: bool = False) -> None:
        render = RENDER.format(before=LOG_ONLY if log_only else "")
        (sandbox.bin / "render.py").write_text(render)
        (sandbox.bin / "pre-commit").write_text(PLANNING_PRE_COMMIT.replace("@TOOLS@", str(REPO / "tools")).replace("@PYTHON@", sys.executable))
        (sandbox.hooks / "pre-commit").write_text("#!/usr/bin/env bash\nexit 0\n")
        sandbox.install("pre-applypatch", "post-applypatch")

    def exploration_patch(self, sandbox: Sandbox, slug: str) -> Path:
        git(sandbox.repo, "checkout", "-q", "-b", slug, sandbox.base)
        fm = {"id": f"EXP-{slug}", "title": "Which one?", "type": "exploration", "status": "open", "summary": "Weighing.", "topic": "deployment-platform"}
        write_doc(sandbox.repo, f"docs/explorations/{slug}.md", fm)
        git(sandbox.repo, "add", "-A")
        git(sandbox.repo, "commit", "-q", "--no-verify", "-m", f"docs: open {slug}")
        out = git(sandbox.repo, "format-patch", "-1", "-o", str(sandbox.patches)).stdout.strip()
        git(sandbox.repo, "checkout", "-q", "main")
        return Path(out)

    def regenerated(self, sandbox: Sandbox) -> str:
        """What CI regenerates from the committed tree."""
        script = sandbox.bin / "render_now.py"
        script.write_text(RENDER.format(before=""))
        env = {**os.environ, "PYTHONPATH": str(REPO / "tools")}
        return subprocess.run([sys.executable, str(script)], cwd=sandbox.repo, check=True, capture_output=True, text=True, env=env).stdout

    def test_the_view_committed_by_git_am_dates_a_new_exploration_and_matches_what_ci_regenerates(self, sandbox: Sandbox) -> None:
        self.planning(sandbox)
        patch = self.exploration_patch(sandbox, "spike")
        before = date.today()
        result = sandbox.am(patch)
        after = date.today()
        assert result.returncode == 0, result.stderr
        view = sandbox.committed("docs/project-planning.md")
        assert view.splitlines()[-1] in {f"| [`spike.md`](explorations/spike.md) | Which one? | {d.isoformat()} |" for d in (before, after)}
        assert view.rstrip("\n") == self.regenerated(sandbox).rstrip("\n")

    def test_control_asking_git_about_commits_only_leaves_a_dash_that_ci_then_changes(self, sandbox: Sandbox) -> None:
        self.planning(sandbox, log_only=True)
        result = sandbox.am(self.exploration_patch(sandbox, "spike"))
        assert result.returncode == 0, result.stderr
        view = sandbox.committed("docs/project-planning.md")
        assert view.splitlines()[-1] == "| [`spike.md`](explorations/spike.md) | Which one? | \u2014 |"
        assert view.rstrip("\n") != self.regenerated(sandbox).rstrip("\n")


EXTRA_VIEW = "docs/extra-view.md"
EXTRA_PRE_COMMIT = """#!/usr/bin/env bash
here="$(dirname "$0")"
. "$here/stash"
regenerate() { "$here/listing" > docs/projects/README.md; "$here/listing" | sed '1s/.*/# Extra/' > docs/extra-view.md; }
if [ "$1" = run ] && [ "$2" = generate-doc-indexes ]; then
  with_unstaged_stashed regenerate
fi
"""
EXTRA_COMMIT_HOOK = """#!/usr/bin/env bash
# Fails when the staged index view or the staged extra view is stale.
cd "$(git rev-parse --show-toplevel)"
. "$STASH"
check() {
  diff <(git show :docs/projects/README.md) <("$LISTING") >/dev/null || { echo "stale view" >&2; return 1; }
  diff <(git show :docs/extra-view.md) <("$LISTING" | sed '1s/.*/# Extra/') >/dev/null || { echo "stale extra view" >&2; return 1; }
}
with_unstaged_stashed check
"""


class TestTheViewList:
    """The hooks take their views from `.githooks/generated-views`, so a view added to that
    one list is staged, regenerated and amended into each commit with no change to a hook."""

    def with_extra_view(self, sandbox: Sandbox, listed: bool) -> None:
        sandbox.install("pre-applypatch", "post-applypatch")
        sandbox.write(EXTRA_VIEW, "# Extra\n")
        (sandbox.bin / "pre-commit").write_text(EXTRA_PRE_COMMIT)
        (sandbox.hooks / "pre-commit").write_text(
            EXTRA_COMMIT_HOOK.replace("$LISTING", str(sandbox.bin / "listing")).replace("$STASH", str(sandbox.bin / "stash"))
        )
        if listed:
            sandbox.write(VIEW_LIST, "\n".join([*VIEWS, EXTRA_VIEW]) + "\n")
        git(sandbox.repo, "add", "-A")
        git(sandbox.repo, "commit", "-q", "--no-verify", "-m", "add the extra view")
        sandbox.base = git(sandbox.repo, "rev-parse", "HEAD").stdout.strip()

    def test_a_view_in_the_list_is_regenerated_into_every_commit_of_a_series(self, sandbox: Sandbox) -> None:
        self.with_extra_view(sandbox, listed=True)
        result = sandbox.am(sandbox.project_patch("alpha"), sandbox.project_patch("beta"))
        assert result.returncode == 0, result.stderr
        assert sandbox.committed(EXTRA_VIEW) == "# Extra\nalpha.md\nbeta.md\n"
        assert sandbox.committed("docs/projects/README.md") == "# Index\nalpha.md\nbeta.md\n"
        assert git(sandbox.repo, "status", "--porcelain").stdout == ""

    def test_control_a_view_left_out_of_the_list_stops_the_apply_on_a_stale_view(self, sandbox: Sandbox) -> None:
        self.with_extra_view(sandbox, listed=False)
        result = sandbox.am(sandbox.project_patch("alpha"))
        assert result.returncode != 0
        assert "stale extra view" in result.stderr
        assert sandbox.count() == 2

    def test_the_hooks_name_no_view_themselves(self) -> None:
        for hook in ("pre-applypatch", "post-applypatch"):
            text = (REPO / ".githooks" / hook).read_text()
            assert "generated-views" in text, hook
            assert not [view for view in VIEWS if view in text], hook


def test_the_list_names_the_views_the_generator_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    written: list[str] = []

    def record(path: Path, heading: str, body: str, *, optional: bool = False) -> bool:
        written.append(path.relative_to(generator.ROOT).as_posix())
        return True

    monkeypatch.setattr(generator, "regenerate", record)
    generator.main()
    assert sorted(set(written)) == sorted(VIEWS)


def test_every_view_in_the_list_exists_in_the_repo() -> None:
    assert VIEWS
    assert all((REPO / view).is_file() for view in VIEWS)
