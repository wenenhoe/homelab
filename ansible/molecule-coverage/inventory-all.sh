#!/usr/bin/env bash
# Regenerates inventory.py's static task inventory for every role with a
# molecule/ folder. Only reads roles/<role>/tasks/, not execution data,
# so it's safe to run any time and doesn't require `molecule test` to
# have run first - re-run after pulling changes to a role's tasks, or
# whenever you're not sure which role's inventory is stale.
#
# Usage:
#   ./inventory-all.sh            # every role with a molecule/ folder
#   ./inventory-all.sh compose    # just one
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

roles=()
if [ "$#" -gt 0 ]; then
    roles=("$@")
else
    for role_dir in roles/*/molecule; do
        [ -d "$role_dir" ] || continue
        roles+=("$(basename "$(dirname "$role_dir")")")
    done
fi

for role in "${roles[@]}"; do
    python3 molecule-coverage/inventory.py "roles/$role" --coverage-dir molecule-coverage/.data
done
