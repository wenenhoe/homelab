"""python3 -m review_criteria BASE HEAD [--repo DIR]

Say whether the change from BASE to HEAD is worth asking for a review, and which criteria say so
(docs/topics/engineering/pr-review.md). It is advice: the exit status is 0 either way.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from review_criteria.criteria import assess, describe, read_changes


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    parser.add_argument("base")
    parser.add_argument("head")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args(argv)
    assessment = assess(read_changes(args.repo, args.base, args.head))
    for line in describe(assessment):
        print(line)
    print("Worth asking for a review." if assessment.recommend else "No criterion calls for a review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
