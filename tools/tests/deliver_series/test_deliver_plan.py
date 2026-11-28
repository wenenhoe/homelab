"""The plan's lines and the numbers its layers take."""

from __future__ import annotations

from pathlib import Path

import pytest
from deliver_series.plan import PlanError, PlannedLayer, check_numbers, numbering_after, parse_plan

TITLE = "feat(tofu): declare the production gateway"


def test_a_plan_is_one_line_per_layer_in_order() -> None:
    plan = parse_plan(f"# a comment\n\ngateway-vm 3 {TITLE}\ndocs-page 1\nlast-one 1 docs(tofu): say it\n")

    assert plan == [PlannedLayer("gateway-vm", 3, TITLE), PlannedLayer("docs-page", 1, None), PlannedLayer("last-one", 1, "docs(tofu): say it")]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        pytest.param("", "names no layer", id="empty"),
        pytest.param("# only a comment\n", "names no layer", id="comments-only"),
        pytest.param("gateway-vm\n", "a line is a slug", id="no-count"),
        pytest.param("Gateway 1\n", "not a branch slug", id="slug-not-kebab"),
        pytest.param("main 1\n", "not a branch slug", id="protected-slug"),
        pytest.param("a-b 1\na-b 1\n", "used twice", id="duplicate-slug"),
        pytest.param("a-b 0\n", "not a number of commits", id="zero-commits"),
        pytest.param("a-b many\n", "not a number of commits", id="count-not-a-number"),
        pytest.param("a-b 27\n", "not a number of commits", id="more-than-the-letters"),
        pytest.param("a-b 2\n", "needs a title", id="several-commits-without-a-title"),
        pytest.param("a-b 2 Add a thing\n", "not a subject", id="title-not-conventional"),
        pytest.param(f"a-b 2 feat(x): {'long ' * 20}\n", "at most 72", id="title-too-long"),
    ],
)
def test_a_plan_that_cannot_be_used_is_refused(text: str, message: str) -> None:
    with pytest.raises(PlanError, match=message):
        parse_plan(text)


def test_numbering_starts_at_one_with_no_earlier_series() -> None:
    assert numbering_after([]) == (1, set())


def test_numbering_follows_the_highest_number_of_the_series_not_merged(tmp_path: Path) -> None:
    series = tmp_path / "earlier.series"
    series.write_bytes(
        b"0007a first-slug\n0008a second-slug\n\n"
        b"From 1111111111111111111111111111111111111111 Mon Sep 17 00:00:00 2001\nSubject: feat: one\nDate: Sat, 28 Nov 2026 10:00:00 +0800\n\nx\n"
        b"From 2222222222222222222222222222222222222222 Mon Sep 17 00:00:00 2001\nSubject: feat: two\nDate: Sat, 28 Nov 2026 10:01:00 +0800\n\ny\n"
    )

    assert numbering_after([series]) == (9, {"first-slug", "second-slug"})


def test_a_series_file_that_cannot_be_read_is_refused(tmp_path: Path) -> None:
    broken = tmp_path / "broken.series"
    broken.write_text("not a series\n")

    with pytest.raises(PlanError, match="cannot read the series file"):
        numbering_after([broken])


def test_a_slug_of_a_series_not_merged_is_not_reused() -> None:
    with pytest.raises(PlanError, match="already used"):
        check_numbers(3, [PlannedLayer("first-slug", 1, None)], {"first-slug"})


def test_the_numbers_stop_at_four_digits() -> None:
    with pytest.raises(PlanError, match="run past 9999"):
        check_numbers(9999, [PlannedLayer("a-b", 1, None), PlannedLayer("c-d", 1, None)], set())
