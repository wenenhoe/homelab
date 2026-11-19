"""Descriptions copied from this repository's Renovate pull requests, so the parser is held to what Renovate writes, not to what a test author remembers."""

from pathlib import Path

import pytest
from renovate_merge import collect, flags
from renovate_merge.changelog import OTHER, Update
from renovate_merge.collect import Pull

BODIES = Path(__file__).parent / "bodies"


def pull(number: int) -> Pull:
    body = (BODIES / f"pr-{number}.txt").read_text(encoding="utf-8")
    return collect.build({"number": number, "title": f"pull {number}", "url": f"https://example.test/pull/{number}", "body": body, "headRefOid": "a" * 40})


def test_a_change_cell_that_is_a_link_and_a_package_with_a_source_link_are_read() -> None:
    found = pull(30)

    assert found.updates == [Update("ghcr.io/renovatebot/renovate", "44.14.1", "44.14.3", OTHER)]
    assert found.notes
    assert found.level == flags.LEVEL_NONE


def test_a_digest_refresh_is_not_read_as_a_major_version() -> None:
    found = pull(862)

    assert [update.new for update in found.updates][:2] == ["4e2425f", "b0be90b"]
    assert len(found.updates) == 9
    assert {update.kind for update in found.updates} == {OTHER}
    assert found.level == flags.LEVEL_NONE


@pytest.mark.parametrize("number", [pytest.param(460, id="digest-pins"), pytest.param(869, id="lockfile-maintenance")])
def test_a_pin_or_lockfile_update_has_no_version_change_and_no_notes(number: int) -> None:
    found = pull(number)

    assert (found.updates, found.notes, found.flags, found.level) == ([], "", [], flags.LEVEL_NONE)


def test_the_repositorys_own_warning_in_a_description_holds_back_a_pull_request() -> None:
    found = pull(780)

    assert [flag.category for flag in found.flags] == ["warning"]
    assert "CODERABBIT_SHA256" in found.flags[0].line
    assert found.notes == ""
    assert found.level == flags.LEVEL_BREAKING
