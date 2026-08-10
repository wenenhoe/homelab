#!/usr/bin/env bash
# Polls every service in a compose stack: waits for a healthy state if a
# healthcheck is defined, or just confirms it's still running after a
# grace period if not. Used by _compose-boot-test.yml (compose-boot-test
# and compose-boot-test-all both call the same reusable workflow) —
# pulled out of an inline `run:` block so it's shellcheck-able and
# diffable on its own instead of living only inside workflow YAML.
#
# Usage: wait-for-compose-health.sh <path-to-compose.yaml>
set -euo pipefail

f="$1"
services=$(docker compose -f "$f" config --services)

for svc in $services; do
  cid=$(docker compose -f "$f" ps -q "$svc")
  [ -n "$cid" ] || { echo "::error::$svc never started"; exit 1; }

  has_hc=$(docker inspect --format='{{if .State.Health}}yes{{end}}' "$cid")
  if [ "$has_hc" = "yes" ]; then
    echo "Waiting for $svc to report healthy..."
    for _ in $(seq 1 30); do
      status=$(docker inspect --format='{{.State.Health.Status}}' "$cid")
      [ "$status" = "healthy" ] && break
      [ "$status" = "unhealthy" ] && { echo "::error::$svc is unhealthy"; docker logs "$cid"; exit 1; }
      sleep 2
    done
    [ "$status" = "healthy" ] || { echo "::error::$svc never became healthy (last: $status)"; docker logs "$cid"; exit 1; }
  else
    # No healthcheck defined — weaker signal, but still catches an
    # immediate crash-loop or bad entrypoint.
    sleep 10
    running=$(docker inspect --format='{{.State.Running}}' "$cid")
    [ "$running" = "true" ] || { echo "::error::$svc exited unexpectedly"; docker logs "$cid"; exit 1; }
  fi
done
