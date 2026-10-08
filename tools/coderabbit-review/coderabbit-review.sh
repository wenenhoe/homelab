#!/usr/bin/env bash
# Run CodeRabbit CLI in a container (no host install) against this repo.
# Usage:
#   ./coderabbit-review.sh auth                    # authenticate (once; persists in ~/.coderabbit)
#   ./coderabbit-review.sh usage                    # cr usage — billing-period review count/spend/reset
#   ./coderabbit-review.sh review [base-branch] [<extra cr flags>]

set -euo pipefail

IMAGE=ghcr.io/wenenhoe/coderabbit-review:latest
AUTH_DIR="$HOME/.coderabbit"

require_git_repo() {
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
    echo "Run this from inside the homelab git repo." >&2
    exit 1
  }
}

# The image has no build-time UID: every container runs as the invoking
# user, so files the CLI writes to the $AUTH_DIR mount stay that user's.
# Root is refused to keep the container non-root, AGENTS.md's standing
# pattern.
docker_run() {
  if [ "$(id -u)" -eq 0 ]; then
    echo "Refusing to run the CodeRabbit container as root." >&2
    exit 1
  fi
  docker run -u "$(id -u):$(id -g)" "$@"
}

cmd_auth() {
  mkdir -p "$AUTH_DIR"
  docker_run -it -v "$AUTH_DIR:/home/coderabbit/.coderabbit/" "$IMAGE" auth login
}

# Confirmed via docs.coderabbit.ai/cli/reference: `usage` (not `stats`,
# which is local review history) reports review count, billing status,
# and — when available — spend and the reset date for the current
# billing period. That's billing-period usage, not confirmed to be an
# hourly-rate-limit counter specifically; run it and see what it shows.
cmd_usage() {
  docker_run -it -v "$AUTH_DIR:/home/coderabbit/.coderabbit/" "$IMAGE" usage
}

# Only allocates a pty when stdin and stdout both are one, so a piped or
# CI invocation gets output free of ANSI control codes.
#
# /workdir is mounted :ro — a review only ever reads the tree to compute a
# diff; the CLI's own local state (auth, review history) lives under
# $AUTH_DIR instead, which stays writable. Least-privilege by default, same
# standing pattern as AGENTS.md's non-root containers.
#
# The mount is the repo root, not $(pwd): from a subdirectory (the setup
# instructions run this from tools/coderabbit-review) a $(pwd) mount has no
# .git, and the CLI exits with "No Git repository found".
run_review_docker() {
  local base="$1"
  shift
  local tty_flags="-i"
  if [ -t 0 ] && [ -t 1 ]; then
    tty_flags="-it"
  fi
  docker_run $tty_flags \
    -v "$AUTH_DIR:/home/coderabbit/.coderabbit/" \
    -v "$(git rev-parse --show-toplevel):/workdir:ro" \
    "$IMAGE" review --base "$base" "$@"
}

cmd_review() {
  require_git_repo
  local base="${1:-main}"
  shift || true
  run_review_docker "$base" "$@"
}

case "${1:-}" in
  auth) cmd_auth ;;
  usage) cmd_usage ;;
  review) shift; cmd_review "$@" ;;
  *)
    echo "Usage: $0 {auth|usage|review [base-branch]}" >&2
    exit 1
    ;;
esac
