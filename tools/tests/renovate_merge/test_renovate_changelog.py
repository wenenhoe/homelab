import pytest
from _bodies import BREAKING_NOTES, PLAIN_NOTES, body
from renovate_merge import changelog
from renovate_merge.changelog import MAJOR, OTHER, PRE_1_0_MINOR, Update


@pytest.mark.parametrize(
    ("old", "new", "kind"),
    [
        pytest.param("1.4.2", "1.4.3", OTHER, id="patch"),
        pytest.param("1.4.2", "1.5.0", OTHER, id="minor"),
        pytest.param("1.9.9", "2.0.0", MAJOR, id="major"),
        pytest.param("v5", "v6", MAJOR, id="bare-tag-major"),
        pytest.param("v5.1.0", "v5.2.0", OTHER, id="v-prefixed-minor"),
        pytest.param("0.12.23", "0.13.0", PRE_1_0_MINOR, id="pre-1-minor"),
        pytest.param("0.12.23", "0.12.24", OTHER, id="pre-1-patch"),
        pytest.param("1.4.2@sha256:" + "a" * 64, "1.4.2@sha256:" + "b" * 64, OTHER, id="digest-refresh-same-tag"),
        pytest.param("1.4.2@sha256:" + "a" * 64, "2.0.0@sha256:" + "b" * 64, MAJOR, id="digest-with-major"),
        pytest.param("sha256:" + "a" * 64, "sha256:" + "b" * 64, OTHER, id="bare-digest"),
        pytest.param("4e2425f", "7d4a888", OTHER, id="short-digests-that-start-with-a-digit"),
        pytest.param("2026-08-08-alpine", "2026-09-22-alpine", OTHER, id="date-tag"),
    ],
)
def test_classify(old: str, new: str, kind: str) -> None:
    assert changelog.classify(old, new) == kind


def test_updates_reads_the_name_and_both_versions_of_each_row() -> None:
    description = body("example/tool", "1.9.9", "2.0.0") + "| [other/dep](https://x.test) | `3.1.0` -> `3.2.0` | | |\n"

    assert changelog.updates(description) == [
        Update("example/tool", "1.9.9", "2.0.0", MAJOR),
        Update("other/dep", "3.1.0", "3.2.0", OTHER),
    ]


def test_updates_ignores_lines_outside_the_table() -> None:
    assert changelog.updates("Bump `1.0.0` → `2.0.0` in prose\n") == []


def test_notes_is_empty_when_the_description_has_none() -> None:
    assert changelog.notes(body("example/tool", "sha256:aaa", "sha256:bbb")) == ""


def test_notes_keeps_the_release_text_and_drops_the_wrapping_and_the_footer() -> None:
    text = changelog.notes(body("example/tool", "1.4.2", "1.4.3", PLAIN_NOTES))

    assert text.startswith("**example/tool (example/tool)**")
    assert "Fix a crash when the config file is empty" in text
    assert not any(marker in text for marker in ("<details>", "</details>", "<summary>", "Configuration", "renovate-debug", "rebase-check"))


def test_notes_drops_a_trailing_separator_when_no_configuration_follows() -> None:
    description = "| a | `1.0.0` → `1.0.1` |\n\n### Release Notes\n\nFixed a thing\n\n---\n"

    assert changelog.notes(description) == "Fixed a thing"


def test_notes_keeps_a_breaking_section_whole() -> None:
    assert "- The `--legacy` flag was removed; use `--compat` instead" in changelog.notes(body("example/tool", "1.9.9", "2.0.0", BREAKING_NOTES))


@pytest.mark.parametrize(
    ("old", "new", "kind"),
    [
        pytest.param("==6.0.3", "==7.0.0", MAJOR, id="pinned-with-double-equals"),
        pytest.param("==6.0.3", "==6.0.4", OTHER, id="pinned-patch"),
        pytest.param("^1.2.3", "^2.0.0", MAJOR, id="caret"),
        pytest.param("~=0.4.1", "~=0.5.0", PRE_1_0_MINOR, id="compatible-release-pre-1"),
        pytest.param(">=3.1", ">=4.0", MAJOR, id="lower-bound"),
    ],
)
def test_classify_reads_a_version_after_a_range_operator(old: str, new: str, kind: str) -> None:
    assert changelog.classify(old, new) == kind


def test_notes_drop_the_invisible_entity_renovate_writes_after_an_at_sign() -> None:
    text = changelog.notes(body("example/tool", "1.4.2", "1.4.3", "Thanks [@&#8203;someone](https://example.test) for [#&#8203;12](https://example.test/12)"))

    assert "[@someone](https://example.test) for [#12](https://example.test/12)" in text
    assert "&#8203;" not in text
