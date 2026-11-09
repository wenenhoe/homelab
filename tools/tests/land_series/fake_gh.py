"""A stand-in `gh` for the land_series tests, put first on PATH as an executable named `gh`.

It keeps its pull requests in the JSON file named by FAKE_GH_STATE and records every call there. `pr merge` really merges the
branch into the bare repository named by FAKE_GH_REMOTE, as GitHub would. FAKE_GH_CHECKS sets what `pr checks` reports:
`pass`, `fail`, or `late` (nothing reported on the first call, then pass).
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
        found = [{"number": pr["number"], "url": pr["url"]} for pr in state["prs"] if pr["head"] == head and pr["open"]]
        print(json.dumps(found))
    elif verb == ["pr", "create"]:
        number = len(state["prs"]) + 1
        url = f"https://example.test/pull/{number}"
        pr = {"number": number, "url": url, "head": option(args, "--head"), "open": True}
        pr["title"], pr["body"] = option(args, "--title"), option(args, "--body")
        state["prs"].append(pr)
        print(url)
    elif verb == ["pr", "edit"]:
        pr = state["prs"][number_of(args[2]) - 1]
        pr["title"], pr["body"] = option(args, "--title"), option(args, "--body")
    elif verb == ["pr", "checks"]:
        state["checks_calls"] += 1
        mode = os.environ.get("FAKE_GH_CHECKS", "pass")
        if mode == "fail" or (mode == "late" and state["checks_calls"] == 1):
            print("no required checks reported on the 'x' branch" if mode == "late" else "build  fail  1m  https://example.test/run", file=sys.stderr)
            save(state)
            return 1
    elif verb == ["pr", "merge"]:
        pr = state["prs"][number_of(args[2]) - 1]
        assert {"--admin", "--merge", "--delete-branch"} <= set(args), args
        with tempfile.TemporaryDirectory() as scratch:
            git("clone", "-q", REMOTE, scratch)
            ahead = git("rev-list", "--count", f"origin/main..origin/{pr['head']}", cwd=scratch)
            git("merge", "-q", "--no-ff", "-m", f"Merge pull request #{pr['number']}", f"origin/{pr['head']}", cwd=scratch)
            git("push", "-q", "origin", "HEAD:main", f":{pr['head']}", cwd=scratch)
        pr["open"] = False
        state["merges"].append({"number": pr["number"], "ahead": int(ahead)})
    else:
        print(f"fake gh: unexpected {args}", file=sys.stderr)
        return 2
    save(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
