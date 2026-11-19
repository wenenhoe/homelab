import pytest
from renovate_merge import flags
from renovate_merge.changelog import MAJOR, OTHER, PRE_1_0_MINOR, Update
from renovate_merge.flags import Flag


@pytest.mark.parametrize(
    ("line", "category"),
    [
        pytest.param("#### ⚠ BREAKING CHANGES", "breaking", id="shouted"),
        pytest.param("This is a breaking change for plugin authors", "breaking", id="lower-case-phrase"),
        pytest.param("The new format is not backwards compatible", "breaking", id="not-backwards-compatible"),
        pytest.param("feat(api)!: drop the v1 endpoint", "breaking", id="conventional-commit-bang"),
        pytest.param("#### ⚠ BREAKING CHANGES", "warning", id="warning-sign"),
        pytest.param("The `--legacy` flag was removed", "removal", id="removed"),
        pytest.param("Drops support for Python 3.9", "removal", id="drops-support"),
        pytest.param("Docker is no longer required", "removal", id="no-longer"),
        pytest.param("`--old` is deprecated", "deprecation", id="deprecated"),
        pytest.param("See the migration guide before upgrading", "migration", id="migration"),
        pytest.param("`timeout` was renamed to `deadline`", "migration", id="renamed"),
        pytest.param("The timeout now defaults to 30 seconds", "default", id="now-defaults"),
        pytest.param("Changed the default for `retries`", "default", id="changed-default"),
    ],
)
def test_scan_names_the_category_of_a_line(line: str, category: str) -> None:
    assert category in {flag.category for flag in flags.scan(line)}


@pytest.mark.parametrize(
    "line",
    [
        pytest.param("Fix a crash when the config file is empty", id="plain-fix"),
        pytest.param("Breaking the build into two jobs", id="word-breaking-alone"),
        pytest.param("Improve the removable media detection hint", id="word-inside-another-word"),
        pytest.param("Bump the bundled certificates", id="bump"),
        pytest.param("- fix: remove stray items keyword from the model", id="routine-fix-that-removes"),
        pytest.param("- [`0ea1cec`](https://example.test/c/0ea1cec) refactor: remove a parameter", id="routine-refactor-with-commit-link"),
        pytest.param("- **workers/global:** migrate flat dashboard CLI flags", id="feature-that-migrates-its-own-flags"),
    ],
)
def test_scan_leaves_ordinary_lines_alone(line: str) -> None:
    assert flags.scan(line) == []


def test_scan_still_reads_a_routine_entry_that_states_a_break() -> None:
    assert {flag.category for flag in flags.scan("- fix!: remove the legacy flag")} == {"breaking"}


def test_scan_cuts_a_long_line_and_collapses_its_spacing() -> None:
    found = flags.scan("removed   " + "x" * 400)

    assert len(found) == 1
    assert found[0].line.startswith("removed x")
    assert len(found[0].line) == flags.MAX_LINE
    assert found[0].line.endswith("…")


def test_scan_reports_a_line_once_for_each_category_it_matches() -> None:
    assert {flag.category for flag in flags.scan("BREAKING: the flag was removed")} == {"breaking", "removal"}


@pytest.mark.parametrize(
    ("changes", "found", "expected"),
    [
        pytest.param([], [], flags.LEVEL_NONE, id="nothing"),
        pytest.param([Update("a", "1.0.0", "1.0.1", OTHER)], [], flags.LEVEL_NONE, id="patch-no-matches"),
        pytest.param([Update("a", "1.0.0", "2.0.0", MAJOR)], [], flags.LEVEL_BREAKING, id="major-alone"),
        pytest.param([], [Flag("breaking", "x")], flags.LEVEL_BREAKING, id="stated-breaking"),
        pytest.param([], [Flag("warning", "x")], flags.LEVEL_BREAKING, id="warning"),
        pytest.param([], [Flag("removal", "x")], flags.LEVEL_NOTABLE, id="removal-alone"),
        pytest.param([Update("a", "0.1.0", "0.2.0", PRE_1_0_MINOR)], [], flags.LEVEL_NOTABLE, id="pre-1-minor"),
        pytest.param([Update("a", "0.1.0", "0.2.0", PRE_1_0_MINOR)], [Flag("breaking", "x")], flags.LEVEL_BREAKING, id="strongest-wins"),
    ],
)
def test_level(changes: list[Update], found: list[Flag], expected: str) -> None:
    assert flags.level(changes, found) == expected
