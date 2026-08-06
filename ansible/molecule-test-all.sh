#!/usr/bin/env bash
# Runs `molecule test --all` for every role with molecule scenarios, one
# role at a time, so it can be invoked from ansible/ instead of `cd`-ing
# into each role directory.
#
# Why not `molecule test --all` directly: Molecule's scenario-discovery
# glob is relative to cwd and doesn't recurse into
# roles/*/molecule/*/molecule.yml on its own. Pointing MOLECULE_GLOB at a
# recursive pattern fixes that but surfaces a second problem — Molecule
# validates scenario names for uniqueness across everything the glob
# discovers, not per-role, and several of this repo's scenarios are named
# "default" (confirmed: fails with "CRITICAL Duplicate scenario name
# 'default' found. Exiting."). Running per-role avoids this, since each
# invocation only sees one role's own already-unique scenario names.
#
# Usage:
#   ./molecule-test-all.sh            # test every role
#   ./molecule-test-all.sh compose    # test just one role
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

roles=()
if [ "$#" -gt 0 ]; then
    roles=("$@")
else
    for role_dir in roles/*/molecule; do
        [ -d "$role_dir" ] || continue
        roles+=("$(basename "$(dirname "$role_dir")")")
    done
fi

failed=()
for role in "${roles[@]}"; do
    echo
    echo "=== $role ==="
    if ! (cd "roles/$role" && molecule test --all); then
        failed+=("$role")
    fi
done

echo
if [ "${#failed[@]}" -eq 0 ]; then
    echo "All roles passed: ${roles[*]}"
else
    echo "FAILED: ${failed[*]}"
    exit 1
fi
