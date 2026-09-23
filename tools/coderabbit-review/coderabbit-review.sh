#!/usr/bin/env bash
# Run CodeRabbit CLI in a container (no host install) against this repo.
# Usage:
#   ./coderabbit-review.sh build                  # build the image (once, or after an update)
#   ./coderabbit-review.sh auth                    # authenticate (once; persists in ~/.coderabbit)
#   ./coderabbit-review.sh usage                    # cr usage — billing-period review count/spend/reset
#   ./coderabbit-review.sh review [base-branch] [-- <extra cr flags>]

set -euo pipefail

IMAGE=coderabbit-cli
DOCKERFILE="$(dirname "$0")/Dockerfile"
AUTH_DIR="$HOME/.coderabbit"

require_git_repo() {
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
    echo "Run this from inside the homelab git repo." >&2
    exit 1
  }
}

cmd_build() {
  docker build --build-arg USER_UID="$(id -u)" -t "$IMAGE" -f "$DOCKERFILE" "$(dirname "$DOCKERFILE")"
}

cmd_auth() {
  mkdir -p "$AUTH_DIR"
  docker run -it -v "$AUTH_DIR:/home/coderabbit/.coderabbit/" "$IMAGE" auth login
}

# Confirmed via docs.coderabbit.ai/cli/reference: `usage` (not `stats`,
# which is local review history) reports review count, billing status,
# and — when available — spend and the reset date for the current
# billing period. That's billing-period usage, not confirmed to be an
# hourly-rate-limit counter specifically; run it and see what it shows.
cmd_usage() {
  docker run -it -v "$AUTH_DIR:/home/coderabbit/.coderabbit/" "$IMAGE" usage
}

# Only allocates a pty when stdin and stdout both are one, so a piped or
# CI invocation gets output free of ANSI control codes.
#
# /workdir is mounted :ro — a review only ever reads the tree to compute a
# diff; the CLI's own local state (auth, review history) lives under
# $AUTH_DIR instead, which stays writable. Least-privilege by default, same
# standing pattern as AGENTS.md's non-root containers.
run_review_docker() {
  local base="$1"
  shift
  local tty_flags="-i"
  if [ -t 0 ] && [ -t 1 ]; then
    tty_flags="-it"
  fi
  docker run $tty_flags \
    -v "$AUTH_DIR:/home/coderabbit/.coderabbit/" \
    -v "$(pwd):/workdir:ro" \
    "$IMAGE" review --base "$base" "$@"
}

cmd_review() {
  require_git_repo
  local base="${1:-main}"
  shift || true
  run_review_docker "$base" "$@"
}

case "${1:-}" in
  build) cmd_build ;;
  auth) cmd_auth ;;
  usage) cmd_usage ;;
  review) shift; cmd_review "$@" ;;
  *)
    echo "Usage: $0 {build|auth|usage|review [base-branch]}" >&2
    exit 1
    ;;
esac
