#!/usr/bin/env bash
# Runs `molecule test` for every role with molecule scenarios, one role
# at a time, so it can be invoked from ansible/ instead of `cd`-ing into
# each role directory. Defaults to every scenario (`--all`); `-s` scopes
# to one named scenario, which only makes sense against a single role -
# scenario names aren't unique across roles (most reuse "default").
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
#   ./molecule-test-all.sh                     # every scenario, every role
#   ./molecule-test-all.sh compose              # every scenario, one role
#   ./molecule-test-all.sh compose caddy        # every scenario, several roles
#   ./molecule-test-all.sh compose -s volumes   # one scenario, one role only
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

usage() {
    echo "Usage: $0 [role...] [-s scenario]" >&2
    echo "-s requires exactly one role - a scenario name is role-specific." >&2
    exit 2
}

scenario=""
roles=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        -s)
            [ "$#" -ge 2 ] || usage
            scenario="$2"
            shift 2
            ;;
        -h | --help)
            usage
            ;;
        *)
            roles+=("$1")
            shift
            ;;
    esac
done

if [ -n "$scenario" ] && [ "${#roles[@]}" -ne 1 ]; then
    usage
fi

if [ "${#roles[@]}" -eq 0 ]; then
    for role_dir in roles/*/molecule; do
        [ -d "$role_dir" ] || continue
        roles+=("$(basename "$(dirname "$role_dir")")")
    done
fi

molecule_args=(test --all)
if [ -n "$scenario" ]; then
    molecule_args=(test -s "$scenario")
fi

# Molecule auto-discovers .config/molecule/config.yml (sets
# ANSIBLE_ROLES_PATH, without which molecule_helpers isn't found) by
# walking up from cwd for a directory literally named .git/.hg/.svn. A
# git-worktree checkout's top-level .git is a file, not a directory, so
# that walk finds nothing there. --base-config sidesteps it entirely;
# git rev-parse resolves correctly for both plain clones and worktrees.
molecule_base_config="$(git rev-parse --show-toplevel)/.config/molecule/config.yml"
molecule_args=(--base-config "$molecule_base_config" "${molecule_args[@]}")

failed=()
for role in "${roles[@]}"; do
    echo
    echo "=== $role${scenario:+ ($scenario)} ==="
    if ! (cd "roles/$role" && molecule "${molecule_args[@]}"); then
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
