#!/usr/bin/env bash
# Determines which compose stacks pr-checks.yml's compose-boot-test job
# should boot-test, given a base and head SHA to diff. Pulled out of
# detect-changes' `run:` block so it's shellcheck-able and diffable on
# its own instead of living only inside workflow YAML (same reasoning as
# wait-for-compose-health.sh's own header comment).
#
# An app is queued when its compose.yaml(.j2) changes, or any file under
# its configs/ or scripts/ directory — the real `compose` role renders
# and stages both into the deploy dir (ansible/roles/compose/tasks/
# init.yaml) before the stack boots, so they change what gets tested.
#
# Exclusion list + per-app reasoning lives in
# .github/compose-boot-test-exclusions.txt — the single source of truth
# shared with pr-checks.yml's compose-syntax-check and
# boot-test-all.yml's list-apps.
#
# Usage: detect-changed-compose-apps.sh <base-sha> <head-sha>
# Writes apps=<json array> to $GITHUB_OUTPUT.
set -euo pipefail

base="$1"
head="$2"
changed=$(git diff --name-only "$base" "$head")
excluded=$(grep -vE '^\s*#|^\s*$' .github/compose-boot-test-exclusions.txt | paste -sd'|' -)

# -f drops deleted compose files (git diff lists them too). A change
# that only deletes configs/ or scripts/ files leaves the app's compose
# file in place, so it is still queued. Templated stacks ship
# compose.yaml.j2 instead of compose.yaml.
apps=()
while IFS= read -r app; do
  [ -f "docker/$app/compose.yaml" ] || [ -f "docker/$app/compose.yaml.j2" ] || continue
  apps+=("$app")
done < <(echo "$changed" \
  | grep -E '^docker/[^/]+/(compose\.yaml(\.j2)?|(configs|scripts)/.+)$' \
  | cut -d/ -f2 \
  | grep -vE "^($excluded)\$" \
  | sort -u)

json=$(printf '%s\n' "${apps[@]:-}" | jq -R . | jq -sc 'map(select(length > 0))')
echo "apps=$json" >> "$GITHUB_OUTPUT"
echo "Boot-testing: $json"
