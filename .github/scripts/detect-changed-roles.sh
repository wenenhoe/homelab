#!/usr/bin/env bash
# Determines which ansible roles pr-checks.yml's molecule job should
# test, given a base and head SHA to diff. Pulled out of detect-changes'
# `run:` block so it's shellcheck-able and diffable on its own instead of
# living only inside workflow YAML (same reasoning as
# wait-for-compose-health.sh's own header comment).
#
# Any file under ansible/roles/<role>/ maps to that role, except three
# repo-wide cases below that queue every role instead — see
# docs/ci.md#change-scoped-not-a-full-sweep for why.
#
# Usage: detect-changed-roles.sh <base-sha> <head-sha>
# Writes roles=<json array> to $GITHUB_OUTPUT.
set -euo pipefail

base="$1"
head="$2"
changed=$(git diff --name-only "$base" "$head")

roles=()
if echo "$changed" | grep -qE '^ansible/requirements\.yml$|^ansible/roles/molecule_helpers/|^pyproject\.toml$|^uv\.lock$'; then
  for d in ansible/roles/*/molecule; do
    [ -d "$d" ] || continue
    roles+=("$(basename "$(dirname "$d")")")
  done
else
  while IFS= read -r role; do
    [ -d "ansible/roles/$role/molecule" ] || continue
    roles+=("$role")
  done < <(echo "$changed" | grep -oE '^ansible/roles/[^/]+' | sed 's#ansible/roles/##' | sort -u)
fi

json=$(printf '%s\n' "${roles[@]:-}" | jq -R . | jq -sc 'map(select(length > 0))')
echo "roles=$json" >> "$GITHUB_OUTPUT"
echo "Testing roles: $json"
