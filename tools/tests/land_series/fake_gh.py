"""A stand-in `gh` for the land_series tests, put first on PATH as an executable named `gh`.

It keeps its pull requests in the JSON file named by FAKE_GH_STATE and records every call there. `pr merge` really merges the
branch into the bare repository named by FAKE_GH_REMOTE, as GitHub would, and refuses when `--match-head-commit` is not the branch's tip.
A pull request whose state has `fork` set is listed as one from another repository. FAKE_GH_CHECKS sets what `pr checks` reports:
`pass`, `fail`, `late` (nothing reported on the first call, then pass), `fail-second` (fail once a second pull request exists), `partial` (only the
first required check is reported on the first call, then all), `never` (only the first required check is ever reported), `pending` (the first required
check is pending on the first call, then passes) or `skipping` (the first required check is skipped). FAKE_GH_REQUIRED lists the required checks, comma
separated (default `build`); FAKE_GH_API=fail makes the rules call fail. `pr checks` prints JSON and exits 8 while anything is pending, as `gh` does.
"""

import json
import os
import subprocess
import sys
import tempfile

STATE = os.environ["FAKE_GH_STATE"]
REMOTE = os.environ["FAKE_GH_REMOTE"]


def load() -> dict:
    try:
        with open(STATE) as handle:
            return json.load(handle)
    except FileNotFoundError:
        return {"prs": [], "calls": [], "merges": [], "checks_calls": 0}


def save(state: dict) -> None:
    with open(STATE, "w") as handle:
        json.dump(state, handle)


def option(args: list[str], name: str) -> str:
    return args[args.index(name) + 1]


def git(*args: str, cwd: str | None = None) -> str:
    identity = ["-c", "user.name=GitHub", "-c", "user.email=noreply@example.invalid", "-c", "commit.gpgsign=false"]
    return subprocess.run(["git", *identity, *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def number_of(reference: str) -> int:
    return int(reference.rstrip("/").rsplit("/", 1)[-1])


def main(args: list[str]) -> int:
    state = load()
    state["calls"].append(args)
    verb = args[:2]
    if verb == ["pr", "list"]:
        head = option(args, "--head")
        found = [
            {"number": pr["number"], "url": pr["url"], "isCrossRepository": pr.get("fork", False)} for pr in state["prs"] if pr["head"] == head and pr["open"]
        ]
        assert "isCrossRepository" in option(args, "--json"), args
        print(json.dumps(found))
    elif verb == ["pr", "create"]:
        number = len(state["prs"]) + 1
        url = f"https://example.test/pull/{number}"
        pr = {"number": number, "url": url, "head": option(args, "--head"), "base": option(args, "--base"), "open": True}
        pr["title"], pr["body"] = option(args, "--title"), option(args, "--body")
        state["prs"].append(pr)
        print(url)
    elif verb == ["pr", "edit"]:
        pr = state["prs"][number_of(args[2]) - 1]
        pr["title"], pr["body"] = option(args, "--title"), option(args, "--body")
    elif args[:1] == ["api"]:
        assert args[1].startswith("repos/{owner}/{repo}/rules/branches/"), args
        if os.environ.get("FAKE_GH_API") == "fail":
            print("HTTP 403: Resource not accessible", file=sys.stderr)
            save(state)
            return 1
        required = [name for name in os.environ.get("FAKE_GH_REQUIRED", "build").split(",") if name]
        rules = [{"type": "deletion"}]
        if required:
            rules.append({"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": name} for name in required]}})
        print(json.dumps(rules))
    elif verb == ["pr", "checks"]:
        state["checks_calls"] += 1
        calls = state["checks_calls"]
        mode = os.environ.get("FAKE_GH_CHECKS", "pass")
        names = [name for name in os.environ.get("FAKE_GH_REQUIRED", "build").split(",") if name]
        assert option(args, "--json") == "name,bucket", args
        if mode == "late" and calls == 1:
            print("no required checks reported on the 'x' branch", file=sys.stderr)
            save(state)
            return 1
        reported = [{"name": name, "bucket": "pass"} for name in names]
        if mode == "fail" or (mode == "fail-second" and len(state["prs"]) >= 2):
            reported[0]["bucket"] = "fail"
        elif mode == "pending" and calls == 1:
            reported[0]["bucket"] = "pending"
        elif mode == "skipping":
            reported[0]["bucket"] = "skipping"
        elif mode == "never" or (mode == "partial" and calls == 1):
            reported = reported[:1]
        print(json.dumps(reported))
        save(state)
        return 8 if any(check["bucket"] == "pending" for check in reported) else 1 if mode.startswith("fail") else 0
    elif verb == ["pr", "merge"]:
        pr = state["prs"][number_of(args[2]) - 1]
        assert {"--admin", "--merge", "--delete-branch"} <= set(args), args
        base = pr["base"]
        head_commit = subprocess.run(["git", "-C", REMOTE, "rev-parse", f"refs/heads/{pr['head']}"], capture_output=True, text=True, check=True).stdout.strip()
        if option(args, "--match-head-commit") != head_commit:
            print("Pull request head commit does not match the expected commit", file=sys.stderr)
            save(state)
            return 1
        with tempfile.TemporaryDirectory() as scratch:
            git("clone", "-q", REMOTE, scratch)
            git("checkout", "-q", "-B", base, f"origin/{base}", cwd=scratch)
            ahead = git("rev-list", "--count", f"origin/{base}..origin/{pr['head']}", cwd=scratch)
            git("merge", "-q", "--no-ff", "-m", f"Merge pull request #{pr['number']}", f"origin/{pr['head']}", cwd=scratch)
            git("push", "-q", "origin", f"HEAD:{base}", f":{pr['head']}", cwd=scratch)
        pr["open"] = False
        state["merges"].append({"number": pr["number"], "ahead": int(ahead)})
    else:
        print(f"fake gh: unexpected {args}", file=sys.stderr)
        return 2
    save(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
