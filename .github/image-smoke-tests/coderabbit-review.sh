#!/usr/bin/env bash
# Smoke test for tools/coderabbit-review/Dockerfile: the CLI it installs is
# the pinned version, git is there for `review`'s diff, and the default user
# is not root. It never runs `review` or `auth`: a review would put findings
# on this repo's Actions log (docs/topics/engineering/coderabbit-review.md).
# Usage: coderabbit-review.sh <image>
set -euo pipefail

image="$1"
dockerfile="$(dirname "$0")/../../tools/coderabbit-review/Dockerfile"

expected="$(sed -n 's/^ARG CODERABBIT_VERSION=//p' "$dockerfile")"
test -n "$expected"
test "$(docker run --rm --entrypoint /bin/coderabbit "$image" --version)" = "$expected"

docker run --rm --entrypoint git "$image" --version
test "$(docker run --rm --entrypoint id "$image" -u)" = 1001
