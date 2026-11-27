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
# roles are worth splitting across runners. When MOLECULE_TIMINGS_FILE is
# set, each row is also written there as tab-separated role, scenario,
# seconds and result, which tools/ci/timing reads.
#
# With -j N, N scenarios run at once, across roles too, on one Docker
# daemon. Each scenario's output is printed whole when it ends, and a role's
# failure starts no further scenario of that role while those already running
# finish. Every scenario's `molecule dependency` runs first, one at a time:
# concurrent installs would write the same Galaxy directory. Times taken this
# way include contention, so -j refuses MOLECULE_TIMINGS_FILE.
#
# Without -s, each role whose scenarios all passed is then held to its floor in
# molecule-coverage/thresholds.yaml, from this run's data alone, and a role
# under it fails the run. Not in GitHub Actions, where a leg runs part of a
# sharded role and the molecule-coverage job gates the whole.
#
# Usage (run from ansible/):
#   ./scripts/molecule-test-all.sh                     # every scenario, every role
#   ./scripts/molecule-test-all.sh compose              # every scenario, one role
#   ./scripts/molecule-test-all.sh compose caddy        # every scenario, several roles
#   ./scripts/molecule-test-all.sh compose -s volumes   # one scenario, one role only
#   ./scripts/molecule-test-all.sh compose -s reset -s build   # several scenarios of one role
#   ./scripts/molecule-test-all.sh -j 4 compose caddy  # four scenarios at once
set -euo pipefail
# One level up from this script's own new location (ansible/scripts/)
# to ansible/ itself - every roles/* path below is relative to that,
# not to this file.
cd "$(dirname "${BASH_SOURCE[0]}")/.."

usage() {
    echo "Usage: $0 [-j jobs] [role...] [-s scenario]..." >&2
    echo "-s requires exactly one role - a scenario name is role-specific." >&2
    exit 2
}

selected=()
roles=()
jobs=1
while [ "$#" -gt 0 ]; do
    case "$1" in
        -s)
            [ "$#" -ge 2 ] || usage
            selected+=("$2")
            shift 2
            ;;
        -j)
            [[ "${2:-}" =~ ^[1-9][0-9]*$ ]] || usage
            jobs=$2
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
if [ "$jobs" -gt 1 ] && [ -n "${MOLECULE_TIMINGS_FILE:-}" ]; then
    echo "-j cannot be used with MOLECULE_TIMINGS_FILE: times taken side by side are not comparable." >&2
    exit 2
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

# Sets `scenarios` to what runs for one role.
scenarios_of() {
    local dir
    if [ "${#selected[@]}" -gt 0 ]; then
        scenarios=("${selected[@]}")
        return
    fi
    scenarios=()
    for dir in "roles/$1"/molecule/*/; do
        [ -f "${dir}molecule.yml" ] || continue
        scenarios+=("$(basename "$dir")")
    done
}

molecule_in() {
    local role=$1
    shift
    (cd "roles/$role" && molecule --base-config "$molecule_base_config" "$@")
}

failed=()
timings=()

# Whether a role is one whose coverage data may be dropped and checked.
has_scenarios() {
    [[ "$1" =~ ^[A-Za-z0-9_-]+$ ]] && [ -d "roles/$1/molecule" ]
}

# Holds one role's collected data to its floor.
coverage_floor() {
    (
        cd molecule-coverage &&
            python3 -m molecule_cov.cli inventory "../roles/$1" --coverage-dir .data &&
            python3 -m molecule_cov.cli report --coverage-dir .data --role "$1" --thresholds-file thresholds.yaml
    )
}

run_serially() {
    local role name started result
    for role in "${roles[@]}"; do
        echo
        echo "=== $role${selected[*]:+ (${selected[*]})} ==="
        scenarios_of "$role"
        for name in "${scenarios[@]}"; do
            echo "--- $role: $name ---"
            started=$SECONDS
            result=passed
            if ! molecule_in "$role" test -s "$name"; then
                result=FAILED
                failed+=("$role")
            fi
            timings+=("$role|$name|$((SECONDS - started))|$result")
            [ "$result" = passed ] || break
        done
    done
}

# One entry per scenario in the order a serial run takes them. state is
# queued, running, finished or skipped.
run_in_parallel() {
    local role name i running=0 left collected
    local job_role=() job_name=() state=() pid=() row=()
    local -A role_failed=()
    work=$(mktemp -d)
    trap 'rm -rf "$work"' EXIT
    trap 'kill $(jobs -p) 2>/dev/null; exit 130' INT TERM

    for role in "${roles[@]}"; do
        scenarios_of "$role"
        for name in "${scenarios[@]}"; do
            job_role+=("$role")
            job_name+=("$name")
            state+=(queued)
        done
    done

    for i in "${!job_role[@]}"; do
        echo "--- dependencies: ${job_role[i]}: ${job_name[i]} ---"
        molecule_in "${job_role[i]}" dependency -s "${job_name[i]}"
    done

    left=${#job_role[@]}
    while [ "$left" -gt 0 ]; do
        for i in "${!job_role[@]}"; do
            [ "${state[i]}" = queued ] || continue
            if [ -n "${role_failed[${job_role[i]}]:-}" ]; then
                state[i]=skipped
                left=$((left - 1))
                continue
            fi
            [ "$running" -lt "$jobs" ] || continue
            echo "--- started: ${job_role[i]}: ${job_name[i]} ---"
            (
                started=$SECONDS
                result=passed
                molecule_in "${job_role[i]}" test -s "${job_name[i]}" >"$work/$i.log" 2>&1 || result=FAILED
                echo "$result $((SECONDS - started))" >"$work/$i.tmp"
                mv "$work/$i.tmp" "$work/$i.status"
            ) &
            pid[i]=$!
            state[i]=running
            running=$((running + 1))
        done

        collected=0
        for i in "${!job_role[@]}"; do
            [ "${state[i]}" = running ] || continue
            if [ ! -f "$work/$i.status" ]; then
                # A job that is gone without a status was killed.
                kill -0 "${pid[i]}" 2>/dev/null && continue
                [ -f "$work/$i.status" ] || echo "FAILED 0" >"$work/$i.status"
            fi
            local result seconds
            read -r result seconds <"$work/$i.status"
            echo
            echo "--- ${job_role[i]}: ${job_name[i]} ($result) ---"
            cat "$work/$i.log"
            row[i]="${job_role[i]}|${job_name[i]}|$seconds|$result"
            if [ "$result" != passed ] && [ -z "${role_failed[${job_role[i]}]:-}" ]; then
                role_failed[${job_role[i]}]=1
                failed+=("${job_role[i]}")
            fi
            state[i]=finished
            running=$((running - 1))
            left=$((left - 1))
            collected=1
        done
        if [ "$collected" -eq 0 ] && [ "$running" -gt 0 ]; then
            wait -n 2>/dev/null || true
        fi
    done
    wait

    for i in "${!job_role[@]}"; do
        [ -z "${row[i]:-}" ] || timings+=("${row[i]}")
    done
}

check_coverage=
if [ "${#selected[@]}" -eq 0 ] && [ -z "${GITHUB_ACTIONS:-}" ]; then
    check_coverage=1
    # A scenario that was renamed or removed would otherwise still count.
    for role in "${roles[@]}"; do
        ! has_scenarios "$role" || rm -rf "molecule-coverage/.data/$role"
    done
fi

if [ "$jobs" -gt 1 ]; then
    run_in_parallel
else
    run_serially
fi

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

if [ -n "${MOLECULE_TIMINGS_FILE:-}" ]; then
    : >"$MOLECULE_TIMINGS_FILE"
    for row in "${timings[@]}"; do
        printf '%s\n' "${row//|/$'\t'}" >>"$MOLECULE_TIMINGS_FILE"
    done
fi

if [ -n "$check_coverage" ]; then
    for role in "${roles[@]}"; do
        has_scenarios "$role" || continue
        [[ " ${failed[*]} " != *" $role "* ]] || continue
        echo
        echo "=== coverage: $role ==="
        coverage_floor "$role" || failed+=("$role (coverage)")
    done
elif [ "${#selected[@]}" -gt 0 ] && [ -z "${GITHUB_ACTIONS:-}" ]; then
    echo
    echo "Coverage not checked: -s runs only some of a role's scenarios."
fi

echo
if [ "${#failed[@]}" -eq 0 ]; then
    echo "All roles passed: ${roles[*]}"
else
    echo "FAILED: ${failed[*]}"
    exit 1
fi
