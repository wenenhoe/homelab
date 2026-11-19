"""A stand-in `gh` for the renovate_merge tests, put first on PATH as an executable named `gh`.

It keeps its state in the JSON file named by FAKE_GH_STATE: `prs` (each with the fields `pr list` returns, plus `state`, and `checks`, a list of
polls, each a list of `[name, bucket]`, of which `pr checks` returns the first and drops it while more remain), `required` (the check names the
rules call returns), `logged_out`, `merge_error`, `created` (what `pr create` was given) and `calls`, every call made.
`pr merge` refuses, as GitHub does, when `--match-head-commit` is not the pull request's head, and otherwise records the merge.
`pr checks` prints JSON and exits 8 while anything is pending, as `gh` does.
"""

import json
import os
import sys

STATE = os.environ["FAKE_GH_STATE"]


def option(args: list[str], name: str) -> str:
    return args[args.index(name) + 1]


def main(args: list[str]) -> int:
    with open(STATE) as handle:
        state = json.load(handle)
    state["calls"].append(args)
    code = run(state, args)
    with open(STATE, "w") as handle:
        json.dump(state, handle)
    return code


def run(state: dict, args: list[str]) -> int:
    verb = args[:2]
    if verb == ["auth", "status"]:
        if state["logged_out"]:
            print("You are not logged into any GitHub hosts. To log in, run: gh auth login", file=sys.stderr)
            return 1
    elif args[:1] == ["api"]:
        assert args[1].startswith("repos/{owner}/{repo}/rules/branches/"), args
        rules = [{"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": name} for name in state["required"]]}}]
        print(json.dumps(rules))
    elif verb == ["pr", "list"]:
        base, wanted = option(args, "--base"), option(args, "--state").upper()
        head = option(args, "--head") if "--head" in args else None
        listed = [pr["listed"] for pr in state["prs"] if pr["state"] == wanted and pr["listed"]["baseRefName"] == base]
        print(json.dumps([pr for pr in listed if head in (None, pr["headRefName"])]))
    elif verb == ["pr", "create"]:
        number = len(state["prs"]) + 1
        url = f"https://example.test/pull/{number}"
        created = {"number": number, "title": option(args, "--title"), "url": url, "body": option(args, "--body"), "headRefName": option(args, "--head")}
        created |= {"headRefOid": "c" * 40, "baseRefName": option(args, "--base"), "isCrossRepository": False, "author": {"login": "someone"}}
        state["prs"].append({"state": "OPEN", "listed": created, "checks": []})
        state.setdefault("created", []).append(created)
        print(url)
    elif verb == ["pr", "view"]:
        pr = state["prs"][int(args[2]) - 1]
        print(json.dumps({"state": pr["state"], "baseRefName": pr["listed"]["baseRefName"], "headRefOid": pr["listed"]["headRefOid"]}))
    elif verb == ["pr", "checks"]:
        pr = state["prs"][int(args[2]) - 1]
        assert option(args, "--json") == "name,bucket", args
        poll = pr["checks"][0]
        if len(pr["checks"]) > 1:
            pr["checks"].pop(0)
        print(json.dumps([{"name": name, "bucket": bucket} for name, bucket in poll]))
        return 8 if any(bucket == "pending" for _, bucket in poll) else 0
    elif verb == ["pr", "merge"]:
        pr = state["prs"][int(args[2]) - 1]
        assert {"--merge", "--delete-branch"} <= set(args) and "--admin" not in args, args
        if state["merge_error"]:
            print(state["merge_error"], file=sys.stderr)
            return 1
        if option(args, "--match-head-commit") != pr["listed"]["headRefOid"]:
            print("Pull request head commit does not match the expected commit", file=sys.stderr)
            return 1
        pr["state"] = "MERGED"
        state["merges"].append(pr["listed"]["number"])
    else:
        print(f"fake gh: unexpected {args}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
