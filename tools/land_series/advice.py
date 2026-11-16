"""Whether a pull request of the series is worth asking for a review, from `review_criteria` (docs/topics/engineering/pr-review.md).

Advice only: a failure to read a diff gives no advice, and nothing here stops a replay or a merge.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

from review_criteria.criteria import assess, describe, read_changes

from land_series.manifest import Pull, group_pulls
from land_series.replay import LayerResult


def advice(repo: Path, tip: str, commits: int) -> list[str]:
    """The lines to print for the pull request whose last commit is `tip` and which has `commits` commits, empty when no review is called for."""
    try:
        assessment = assess(read_changes(str(repo), f"{tip}~{commits}", tip))
    except subprocess.CalledProcessError, OSError:
        return []
    if not assessment.recommend:
        return []
    return ["Worth asking for a review:", *(f"  {line}" for line in describe(assessment)), "  How to ask: docs/topics/engineering/pr-review.md"]


def replay_advice(repo: Path, results: Sequence[LayerResult]) -> list[str]:
    """The advice for each pull request the replay applied in full, headed by the pull request."""
    lines: list[str] = []
    for pull in group_pulls([result.layer for result in results if result.applied]):
        commits = {result.layer.id: result.commit for result in results if result.applied}
        tip = commits[pull.layers[-1].id]
        if not tip:
            continue
        found = advice(repo, tip, len(pull.layers))
        if found:
            lines += [f"Pull request {pull.number} ({pull.title}):", *found]
    return lines


def kept_advice(repo: Path, pull: Pull, branch: str) -> list[str]:
    """The advice for a pull request whose kept branch is `branch`."""
    return advice(repo, branch, len(pull.layers))
