#!/usr/bin/env bash
set -e

# Function to handle exit signal
handle_exit_signal() {
  # Capture the exit code immediately
  STATUS=$?

  if [ $STATUS -eq 0 ]; then
    echo "Upgrade is successful."
  else
    echo "Upgrade failed with exit code: $STATUS"
  fi
}

# Intercept exit signal
trap handle_exit_signal EXIT

# Use the first argument passed to the script, or default to 26.1.2 if empty
VERSION="${1:-26.1.2}"

echo "Starting test-upgrade with VERSION=${VERSION}..."

# Modify log level to hide the orphan container warning
VERSION="$VERSION" docker --log-level ERROR compose \
  -f compose.yaml \
  -f compose.upgrade.yaml \
  run --rm test-upgrade
