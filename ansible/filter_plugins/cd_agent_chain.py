"""cd_agent_chain_errors: what is wrong with the successor links between CD agent jobs.

ADR 0074 lets a job name successors that systemd starts when it ends. The
cd_agent role refuses to provision a chain that can never work or never
stops, so it asks this filter for the problems and stops if there are any.
Pure Python over the job list the role was given, so it is tested directly
(ansible/tests/test_cd_agent_chain.py) rather than through an Ansible run.
"""

from __future__ import annotations

from typing import Any


def _has_timer(job: dict[str, Any]) -> bool:
    return job.get("poll_interval") is not None or job.get("on_calendar") is not None


def _cycle_from(start: str, successors: dict[str, list[str]], done: set[str]) -> list[str] | None:
    """The first cycle reachable from `start`, as a path that ends where it began, or None."""
    path: list[str] = []
    on_path: set[str] = set()

    def visit(name: str) -> list[str] | None:
        if name in on_path:
            return [*path[path.index(name) :], name]
        if name in done:
            return None
        path.append(name)
        on_path.add(name)
        for successor in successors[name]:
            if successor in successors and (cycle := visit(successor)):
                return cycle
        path.pop()
        on_path.discard(name)
        done.add(name)
        return None

    cycle = visit(start)
    if cycle:
        done.update(path)  # reported once, not again from each of its other members
    return cycle


def cd_agent_chain_errors(jobs: list[dict[str, Any]]) -> list[str]:
    """One message per problem: a malformed or unknown successor, a cycle, a job nothing starts."""
    errors: list[str] = []
    successors: dict[str, list[str]] = {}
    for job in jobs:
        links = job.get("successors", [])
        if not isinstance(links, list) or not all(isinstance(link, str) for link in links):
            errors.append(f"the successors of {job['name']} must be a list of job names")
            links = []
        successors[job["name"]] = links

    for name, links in successors.items():
        errors.extend(f"{name} names successor {link}, which is not a job" for link in links if link not in successors)

    done: set[str] = set()
    for name in successors:
        if cycle := _cycle_from(name, successors, done):
            errors.append(f"jobs form a cycle: {' -> '.join(cycle)}")

    started = {link for links in successors.values() for link in links}
    errors.extend(
        f"{job['name']} has no timer and no predecessor, so nothing ever starts it" for job in jobs if not _has_timer(job) and job["name"] not in started
    )
    return errors


class FilterModule:
    def filters(self) -> dict[str, Any]:
        return {"cd_agent_chain_errors": cd_agent_chain_errors}
