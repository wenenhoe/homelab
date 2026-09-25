#!/usr/bin/env bash
# Determines which compose stacks pr-checks.yml's compose-boot-test job
# should boot-test, given a base and head SHA to diff. Pulled out of
# detect-changes' `run:` block so it's shellcheck-able and diffable on
# its own instead of living only inside workflow YAML (same reasoning as
# wait-for-compose-health.sh's own header comment).
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

# -f drops deleted compose files (git diff lists them too) — same guard
# detect-changed-roles.sh applies via -d. Templated stacks ship
# compose.yaml.j2 instead of compose.yaml.
apps=()
while IFS= read -r app; do
  [ -f "docker/$app/compose.yaml" ] || [ -f "docker/$app/compose.yaml.j2" ] || continue
  apps+=("$app")
done < <(echo "$changed" \
  | grep -oE '^docker/[^/]+/compose\.yaml(\.j2)?$' \
  | sed -E 's#docker/([^/]+)/compose\.yaml(\.j2)?#\1#' \
  | grep -vE "^($excluded)\$" \
  | sort -u)

json=$(printf '%s\n' "${apps[@]:-}" | jq -R . | jq -sc 'map(select(length > 0))')
echo "apps=$json" >> "$GITHUB_OUTPUT"
echo "Boot-testing: $json"
