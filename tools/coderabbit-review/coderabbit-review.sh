#!/usr/bin/env bash
# Run CodeRabbit CLI in a container (no host install) against this repo.
# Usage:
#   ./coderabbit-review.sh auth                    # authenticate (once; persists in ~/.coderabbit)
#   CODERABBIT_API_KEY=... ./coderabbit-review.sh auth --api-key   # headless: no browser step
#   ./coderabbit-review.sh usage                    # cr usage — billing-period review count/spend/reset
#   ./coderabbit-review.sh review [base-branch] [-- <extra cr flags>]

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
  case "${1:-}" in
    "") docker_run -it -v "$AUTH_DIR:/home/coderabbit/.coderabbit/" "$IMAGE" auth login ;;
    --api-key) cmd_auth_api_key ;;
    *)
      echo "Usage: $0 auth [--api-key]" >&2
      exit 1
      ;;
  esac
}

# The CLI's only documented headless form is `auth login --api-key "<key>"`.
# The key comes from the environment and is forwarded with a bare
# `-e NAME`, so its value never appears in this script's arguments or the
# host's `docker run` argv; the container's shell expands it into the CLI's
# own argv instead. It needs an Agentic API key, not a user one.
cmd_auth_api_key() {
  if [ -z "${CODERABBIT_API_KEY:-}" ]; then
    echo "CODERABBIT_API_KEY is not set (an Agentic API key from the CodeRabbit dashboard)." >&2
    exit 1
  fi
  # shellcheck disable=SC2016 # $CODERABBIT_API_KEY must expand inside the container, not here.
  docker_run -e CODERABBIT_API_KEY \
    -v "$AUTH_DIR:/home/coderabbit/.coderabbit/" \
    --entrypoint /bin/sh "$IMAGE" \
    -c 'exec /bin/coderabbit auth login --api-key "$CODERABBIT_API_KEY"'
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
  auth) shift; cmd_auth "$@" ;;
  usage) cmd_usage ;;
  review) shift; cmd_review "$@" ;;
  *)
    echo "Usage: $0 {auth [--api-key]|usage|review [base-branch]}" >&2
    exit 1
    ;;
esac
