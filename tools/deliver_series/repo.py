"""What the checkout must be before a series is built from it: on the tip of the base, clean, with commits of its own."""

from __future__ import annotations

from pathlib import Path

from land_series.run import CommandError, checked, run

from deliver_series.form import Commit
from deliver_series.repository import HOMELAB, Identity

FETCH_SECONDS = 300
LISTED_FILES = 10
_FIELDS = "%an%x00%ae%x00%cn%x00%ce%x00%ai%x00%ci%x00%B"


class RepoError(Exception):
    """The checkout cannot be built from."""


def git(repo: Path, *args: str, timeout: float | None = None) -> str:
    try:
        return checked(["git", "-C", str(repo), *args], timeout=timeout).text
    except CommandError as error:
        raise RepoError(str(error)) from error


def toplevel(repo: Path) -> Path:
    return Path(git(repo, "rev-parse", "--show-toplevel")).resolve()


def require_clean(repo: Path) -> None:
    """Refuse a tree with a change that is staged, unstaged or untracked: the series holds commits, so such a change would be left out of it."""
    changed = git(repo, "status", "--porcelain", "--untracked-files=all").splitlines()
    if changed:
        listed = "; ".join(line[3:] for line in changed[:LISTED_FILES])
        more = f" and {len(changed) - LISTED_FILES} more" if len(changed) > LISTED_FILES else ""
        raise RepoError(f"the working tree has changes ({listed}{more}); commit or remove them")


def fetch_base(repo: Path, base: str) -> str:
    """Fetch the base branch and return `origin/<base>`."""
    ref = f"{HOMELAB.remote}/{base}"
    git(repo, "fetch", "--quiet", HOMELAB.remote, f"+refs/heads/{base}:refs/remotes/{ref}", timeout=FETCH_SECONDS)
    return ref


def require_on_tip(repo: Path, ref: str) -> None:
    """Refuse a branch that does not hold the tip of the base: a series built on an older base is replayed and landed on another."""
    if run(["git", "-C", str(repo), "merge-base", "--is-ancestor", ref, "HEAD"]).returncode != 0:
        behind = git(repo, "rev-list", "--count", f"HEAD..{ref}")
        raise RepoError(f"the branch is not on the tip of {ref} ({behind} commits of it are missing); rebase it, then build again")


def maintainer(repo: Path, ref: str) -> Identity:
    """The author of the newest commit on the base that is not a bot's."""
    for line in git(repo, "log", ref, "--no-merges", "--format=%an%x00%ae").splitlines():
        name, _, email = line.partition("\0")
        if "[bot]" not in line:
            return Identity(name, email)
    raise RepoError(f"{ref} has no commit by anyone but a bot, so the maintainer's identity is unknown (is the clone shallow?)")


def commits_on_top(repo: Path, ref: str) -> list[Commit]:
    """The commits above the base, oldest first. A merge is refused: a series is a line of commits."""
    shas = git(repo, "rev-list", "--reverse", "--parents", f"{ref}..HEAD").splitlines()
    commits = []
    for line in shas:
        sha, *parents = line.split()
        if len(parents) != 1:
            raise RepoError(f"{sha[:12]} is a merge; rebase the branch so it holds only single-parent commits")
        fields = git(repo, "show", "-s", f"--format={_FIELDS}", sha).split("\0", 6)
        an, ae, cn, ce, author_date, committer_date, message = fields
        commits.append(Commit(sha, Identity(an, ae), Identity(cn, ce), author_date, committer_date, message.strip()))
    return commits


def patch_of(repo: Path, sha: str) -> bytes:
    """The commit as one `git format-patch` message with no number in its subject."""
    done = run(["git", "-C", str(repo), "format-patch", "--stdout", "--no-numbered", "--no-signature", "-1", sha])
    if done.returncode != 0:
        raise RepoError(f"cannot write the patch of {sha[:12]}: {done.output}")
    return done.stdout


def changed_paths(repo: Path, sha: str) -> list[str]:
    """Every path the commit changes, a rename counted as a removal and an addition."""
    listed = checked(["git", "-C", str(repo), "diff", "--no-renames", "--name-only", "-z", f"{sha}^", sha]).stdout
    return [path.decode("utf-8", errors="surrogateescape") for path in listed.split(b"\0") if path]


def origin_url(repo: Path) -> str:
    return git(repo, "remote", "get-url", HOMELAB.remote)


def rev(repo: Path, ref: str) -> str:
    return git(repo, "rev-parse", ref)
