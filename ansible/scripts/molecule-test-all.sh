#!/usr/bin/env bash
# Runs `molecule test` for every role with molecule scenarios, one role
# at a time, so it can be invoked from ansible/ instead of `cd`-ing into
# each role directory. Defaults to every scenario (`--all`); `-s` scopes
# to the named scenarios (repeat it for several), which only makes sense
# against a single role - scenario names aren't unique across roles (most
# reuse "default"). A CI shard of a large role runs this way.
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
# Without -s each scenario runs as its own `molecule test -s <name>`, in
# name order and stopping at a role's first failure like --all does, so
# the run can time every scenario. The timings print as a table and, when
# GITHUB_STEP_SUMMARY is set, land in the job summary: they show which
# roles are worth splitting across runners.
#
# Usage (run from ansible/):
#   ./scripts/molecule-test-all.sh                     # every scenario, every role
#   ./scripts/molecule-test-all.sh compose              # every scenario, one role
#   ./scripts/molecule-test-all.sh compose caddy        # every scenario, several roles
#   ./scripts/molecule-test-all.sh compose -s volumes   # one scenario, one role only
#   ./scripts/molecule-test-all.sh compose -s reset -s build   # several scenarios of one role
set -euo pipefail
# One level up from this script's own new location (ansible/scripts/)
# to ansible/ itself - every roles/* path below is relative to that,
# not to this file.
cd "$(dirname "${BASH_SOURCE[0]}")/.."

usage() {
    echo "Usage: $0 [role...] [-s scenario]..." >&2
    echo "-s requires exactly one role - a scenario name is role-specific." >&2
    exit 2
}

selected=()
roles=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        -s)
            [ "$#" -ge 2 ] || usage
            selected+=("$2")
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

if [ "${#selected[@]}" -gt 0 ] && [ "${#roles[@]}" -ne 1 ]; then
    usage
fi

if [ "${#roles[@]}" -eq 0 ]; then
    for role_dir in roles/*/molecule; do
        [ -d "$role_dir" ] || continue
        roles+=("$(basename "$(dirname "$role_dir")")")
    done
fi

# Molecule auto-discovers .config/molecule/config.yml (sets
# ANSIBLE_ROLES_PATH, without which molecule_helpers isn't found) by
# walking up from cwd for a directory literally named .git/.hg/.svn. A
# git-worktree checkout's top-level .git is a file, not a directory, so
# that walk finds nothing there. --base-config sidesteps it entirely;
# git rev-parse resolves correctly for both plain clones and worktrees.
molecule_base_config="$(git rev-parse --show-toplevel)/.config/molecule/config.yml"

failed=()
timings=()
for role in "${roles[@]}"; do
    echo
    echo "=== $role${selected[*]:+ (${selected[*]})} ==="
    if [ "${#selected[@]}" -gt 0 ]; then
        scenarios=("${selected[@]}")
    else
        scenarios=()
        for dir in "roles/$role"/molecule/*/; do
            [ -f "${dir}molecule.yml" ] || continue
            scenarios+=("$(basename "$dir")")
        done
    fi
    for name in "${scenarios[@]}"; do
        echo "--- $role: $name ---"
        started=$SECONDS
        result=passed
        if ! (cd "roles/$role" && molecule --base-config "$molecule_base_config" test -s "$name"); then
            result=FAILED
            failed+=("$role")
        fi
        timings+=("$role|$name|$((SECONDS - started))|$result")
        [ "$result" = passed ] || break
    done
done

table="| Role | Scenario | Seconds | Result |"$'\n'"| :--- | :--- | ---: | :--- |"
for row in "${timings[@]}"; do
    IFS='|' read -r t_role t_scenario t_seconds t_result <<<"$row"
    table+=$'\n'"| $t_role | $t_scenario | $t_seconds | $t_result |"
done
echo
echo "$table"
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    printf '### Molecule scenario timings\n\n%s\n' "$table" >>"$GITHUB_STEP_SUMMARY"
fi

echo
if [ "${#failed[@]}" -eq 0 ]; then
    echo "All roles passed: ${roles[*]}"
else
    echo "FAILED: ${failed[*]}"
    exit 1
fi
