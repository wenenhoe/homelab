#!/usr/bin/env bash
# Runs `molecule test --all` for every role that has molecule scenarios,
# one role at a time, so it can be invoked from ansible/ instead of
# needing to `cd` into each role directory individually.
#
# Why not just `molecule test --all` from here directly: Molecule's
# scenario discovery glob (molecule/*/molecule.yml) is relative to cwd
# and doesn't recurse into roles/*/molecule/*/molecule.yml on its own -
# MOLECULE_GLOB can be pointed at a recursive pattern to fix that part,
# but doing so surfaces a second, real problem: Molecule validates
# scenario names for uniqueness across everything the glob discovers, not
# per-role, and 6 of this repo's 11 scenarios are named "default" (apt,
# bind9, caddy, compose, compose_app, docker) - confirmed via real-world
# reports that this fails with "CRITICAL Duplicate scenario name
# 'default' found. Exiting." Running molecule per-role, one directory at
# a time, avoids this entirely since each invocation only ever sees one
# role's own (already-unique) scenario names.
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
