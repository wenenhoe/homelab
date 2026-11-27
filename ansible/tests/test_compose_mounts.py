"""Unit tests for filter_plugins/compose_mounts.py.

Run via `uv run pytest ansible/tests/ -v`. Both filters are pure functions, so
they are imported directly rather than through an Ansible run.
"""

from __future__ import annotations

from pathlib import Path

import compose_mounts as filter_mod
import pytest
import yaml
from ansible.errors import AnsibleFilterError

REPO = Path(__file__).resolve().parents[2]
STACK = "/opt/stacks/app"
LABEL = filter_mod.LABEL

compose_mounts = filter_mod.compose_mounts
compose_mounts_override = filter_mod.compose_mounts_override


def compose(*volumes, service="web"):
    return yaml.safe_dump({"services": {service: {"image": "x", "volumes": list(volumes)}}})


MOUNT_CASES = {
    "short read-only file": (compose("./Caddyfile:/etc/caddy/Caddyfile:ro"), {"web": ["Caddyfile"]}),
    "short read-only directory": (compose("./conf.d:/etc/conf.d:ro"), {"web": ["conf.d"]}),
    "short with several options": (compose("./a.hcl:/etc/a.hcl:ro,z"), {"web": ["a.hcl"]}),
    "short without ro": (compose("./a.hcl:/etc/a.hcl"), {}),
    "short with another option": (compose("./a.hcl:/etc/a.hcl:rw"), {}),
    "short with a default in the target": (compose("./a.hcl:${TARGET:-/etc/a.hcl}:ro"), {"web": ["a.hcl"]}),
    "short with a default in the target and no ro": (compose("./a.hcl:${TARGET:-/etc/a.hcl}"), {}),
    "short with a default in the target and ro among options": (compose("./a.hcl:${TARGET:-/etc/a.hcl}:ro,z"), {"web": ["a.hcl"]}),
    "short with a default in a writable source": (compose("${CONF:-./a.hcl}:/etc/a.hcl"), {}),
    "short with a default in a writable source and rw": (compose("${CONF:-./a.hcl}:/etc/a.hcl:rw"), {}),
    "short with only the z option": (compose("./a.hcl:/etc/a.hcl:z"), {}),
    "long read-only": (compose({"type": "bind", "source": "./a.sh", "target": "/a.sh", "read_only": True}), {"web": ["a.sh"]}),
    "long writable": (compose({"type": "bind", "source": "./a.sh", "target": "/a.sh"}), {}),
    "long read_only false": (compose({"type": "bind", "source": "./a.sh", "target": "/a.sh", "read_only": False}), {}),
    "long volume with subpath": (
        compose({"type": "volume", "source": "caddyfile", "target": "/c", "read_only": True, "volume": {"subpath": "Caddyfile"}}),
        {},
    ),
    "named volume": (compose("data:/data:ro"), {}),
    "docker socket": (compose("/var/run/docker.sock:/var/run/docker.sock:ro"), {}),
    "absolute path outside the stack": (compose("/etc/localtime:/etc/localtime:ro"), {}),
    "absolute path inside the stack": (compose(f"{STACK}/a.hcl:/a.hcl:ro"), {"web": ["a.hcl"]}),
    "path that leaves the stack": (compose("../other/a.hcl:/a.hcl:ro"), {}),
    "sibling directory with the same prefix": (compose(f"{STACK}-two/a.hcl:/a.hcl:ro"), {}),
    "path that returns into the stack": (compose("./x/../a.hcl:/a.hcl:ro"), {"web": ["a.hcl"]}),
    "the stack directory itself": (compose(".:/stack:ro"), {}),
    "home directory": (compose("~/a.hcl:/a.hcl:ro"), {}),
    "nested file": (compose("./scripts/run.sh:/run.sh:ro"), {"web": ["scripts/run.sh"]}),
    "duplicates collapse and sort": (compose("./b:/b:ro", "./a:/a:ro", "./b:/c:ro"), {"web": ["a", "b"]}),
    "no volumes": (yaml.safe_dump({"services": {"web": {"image": "x"}}}), {}),
    "no services": ("name: x\n", {}),
    "empty file": ("", {}),
}


@pytest.mark.parametrize(("text", "expected"), MOUNT_CASES.values(), ids=MOUNT_CASES.keys())
def test_compose_mounts(text, expected):
    assert compose_mounts(text, STACK) == expected


def test_compose_mounts_keeps_each_service_apart():
    text = yaml.safe_dump(
        {
            "services": {
                "one": {"volumes": ["./a:/a:ro"]},
                "two": {"volumes": ["./b:/b:ro", "data:/d"]},
                "three": {"volumes": ["data:/d"]},
            }
        }
    )
    assert compose_mounts(text, STACK) == {"one": ["a"], "two": ["b"]}


def test_compose_mounts_ignores_a_trailing_slash_on_the_stack_directory():
    assert compose_mounts(compose("./a:/a:ro"), f"{STACK}/") == {"web": ["a"]}


def test_compose_mounts_refuses_a_variable_in_a_read_only_source():
    with pytest.raises(AnsibleFilterError, match=r"mount source '\$\{CONF\}/a' of service 'web' holds a variable"):
        compose_mounts(compose("${CONF}/a:/a:ro"), STACK)


@pytest.mark.parametrize(
    "mount",
    [
        pytest.param("${CONF:-./a}:/a:ro", id="default in the source"),
        pytest.param("${CONF:-./a}:${TARGET:-/a}:ro", id="default in the source and the target"),
        pytest.param("${CONF:?set CONF}/a:/a:ro,z", id="required variable in the source"),
    ],
)
def test_compose_mounts_refuses_a_default_in_a_read_only_source(mount):
    with pytest.raises(AnsibleFilterError, match=r"mount source '\$\{CONF:[^']*' of service 'web' holds a variable"):
        compose_mounts(compose(mount), STACK)


def test_compose_mounts_allows_a_variable_in_a_writable_source():
    assert compose_mounts(compose("${DATA}/a:/a"), STACK) == {}


@pytest.mark.parametrize(
    ("text", "match"),
    [
        pytest.param("services: [", "does not parse", id="invalid yaml"),
        pytest.param("services: [a]", "'services' must be a mapping", id="services not a mapping"),
        pytest.param(5, "expected the compose file's text", id="not text"),
    ],
)
def test_compose_mounts_refuses_what_it_cannot_read(text, match):
    with pytest.raises(AnsibleFilterError, match=match):
        compose_mounts(text, STACK)


def test_every_compose_file_in_the_repo_parses(subtests):
    """A deployed file is rendered from a template, so only the plain ones are read; each plain one must yield a mapping."""
    for path in sorted((REPO / "docker").glob("*/compose*.yaml")):
        with subtests.test(path=str(path.relative_to(REPO))):
            assert isinstance(compose_mounts(path.read_text(), STACK), dict)


def stat_result(path, *, checksum=None, exists=True, isdir=False, root=STACK):
    return {"item": path, "stat": {"path": f"{root}/{path}", "exists": exists, "isdir": isdir, "checksum": checksum}}


def find_result(stat, files):
    return {"item": stat, "files": [{"path": f"{stat['stat']['path']}/{name}", "checksum": checksum} for name, checksum in files]}


def label_of(text, service="web"):
    return yaml.safe_load(text)["services"][service]["labels"][LABEL]


def test_override_is_empty_for_an_app_with_no_mounts():
    assert compose_mounts_override({}, [], []) == ""


def test_override_labels_each_service_with_a_sha256():
    mounts = {"web": ["a"], "db": ["b"]}
    text = compose_mounts_override(mounts, [stat_result("a", checksum="1"), stat_result("b", checksum="2")], [])
    document = yaml.safe_load(text)
    assert set(document["services"]) == {"web", "db"}
    labels = {name: service["labels"][LABEL] for name, service in document["services"].items()}
    assert all(len(value) == 64 and set(value) <= set("0123456789abcdef") for value in labels.values())
    assert labels["web"] != labels["db"]


def test_override_is_stable_for_the_same_content():
    results = [stat_result("a", checksum="1"), stat_result("b", checksum="2")]
    first = compose_mounts_override({"web": ["a", "b"]}, results, [])
    second = compose_mounts_override({"web": ["b", "a"]}, list(reversed(results)), [])
    assert first == second


def test_override_changes_with_a_changed_file():
    before = compose_mounts_override({"web": ["a"]}, [stat_result("a", checksum="1")], [])
    after = compose_mounts_override({"web": ["a"]}, [stat_result("a", checksum="2")], [])
    assert label_of(before) != label_of(after)


def test_override_changes_only_for_the_service_that_mounts_the_file():
    mounts = {"web": ["a"], "db": ["b"]}
    before = yaml.safe_load(compose_mounts_override(mounts, [stat_result("a", checksum="1"), stat_result("b", checksum="2")], []))
    after = yaml.safe_load(compose_mounts_override(mounts, [stat_result("a", checksum="1"), stat_result("b", checksum="3")], []))
    assert before["services"]["web"] == after["services"]["web"]
    assert before["services"]["db"] != after["services"]["db"]


def test_override_changes_when_two_files_swap_checksums():
    one = compose_mounts_override({"web": ["a", "b"]}, [stat_result("a", checksum="1"), stat_result("b", checksum="2")], [])
    swapped = compose_mounts_override({"web": ["a", "b"]}, [stat_result("a", checksum="2"), stat_result("b", checksum="1")], [])
    assert label_of(one) != label_of(swapped)


def test_override_reads_a_directory_through_its_files():
    directory = stat_result("conf.d", isdir=True)
    before = compose_mounts_override({"web": ["conf.d"]}, [directory], [find_result(directory, [("a", "1"), ("b", "2")])])
    changed = compose_mounts_override({"web": ["conf.d"]}, [directory], [find_result(directory, [("a", "1"), ("b", "3")])])
    added = compose_mounts_override({"web": ["conf.d"]}, [directory], [find_result(directory, [("a", "1"), ("b", "2"), ("c", "4")])])
    renamed = compose_mounts_override({"web": ["conf.d"]}, [directory], [find_result(directory, [("a", "1"), ("z", "2")])])
    assert len({label_of(text) for text in (before, changed, added, renamed)}) == 4


def test_override_tells_an_empty_directory_from_a_missing_one():
    empty = stat_result("conf.d", isdir=True)
    missing = stat_result("conf.d", exists=False)
    assert label_of(compose_mounts_override({"web": ["conf.d"]}, [empty], [find_result(empty, [])])) != label_of(
        compose_mounts_override({"web": ["conf.d"]}, [missing], [])
    )


def test_override_changes_when_a_missing_file_appears():
    missing = compose_mounts_override({"web": ["a"]}, [stat_result("a", exists=False)], [])
    present = compose_mounts_override({"web": ["a"]}, [stat_result("a", checksum="1")], [])
    assert label_of(missing) != label_of(present)


def test_override_pairs_each_directory_with_its_own_files():
    first, second = stat_result("one", isdir=True), stat_result("two", isdir=True)
    finds = [find_result(first, [("f", "1")]), find_result(second, [("f", "2")])]
    swapped = [find_result(first, [("f", "2")]), find_result(second, [("f", "1")])]
    mounts = {"web": ["one"], "db": ["two"]}
    assert compose_mounts_override(mounts, [first, second], finds) != compose_mounts_override(mounts, [first, second], swapped)


def test_override_refuses_a_mount_with_no_stat_result():
    with pytest.raises(AnsibleFilterError, match=r"no stat result for \['b'\] of service 'web'"):
        compose_mounts_override({"web": ["a", "b"]}, [stat_result("a", checksum="1")], [])


def test_override_refuses_mounts_that_are_not_a_mapping():
    with pytest.raises(AnsibleFilterError, match="expected the mounts mapping"):
        compose_mounts_override(["a"], [], [])
