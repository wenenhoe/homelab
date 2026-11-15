from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from scratch_run import settings
from scratch_run.settings import SettingsError, init_env_file, merge, read_env_file

REPO = Path(__file__).resolve().parents[3]


def write(directory: Path, text: str, mode: int = 0o600) -> Path:
    path = directory / "scratch-run.env"
    path.write_text(text)
    path.chmod(mode)
    return path


def test_lines_are_read_as_keys_and_values(tmp_path):
    path = write(tmp_path, "# a comment\n\nNODE=root@pve\nPROXMOX_API_TOKEN=u@pam!id=se=cret\nQUOTED=\"a b\"\nSINGLE='c'\nEMPTY=\nHOME_DIR=~/x\n")
    assert read_env_file(path, REPO) == {
        "NODE": "root@pve",
        "PROXMOX_API_TOKEN": "u@pam!id=se=cret",
        "QUOTED": "a b",
        "SINGLE": "c",
        "HOME_DIR": str(Path.home() / "x"),
    }


@pytest.mark.parametrize(
    ("text", "message"),
    [
        pytest.param("not a pair\n", "line 1 is not KEY=VALUE", id="no-equals"),
        pytest.param("NODE=a\nlower=b\n", "line 2 is not KEY=VALUE", id="lower-case-key"),
        pytest.param("=x\n", "line 1 is not KEY=VALUE", id="empty-key"),
    ],
)
def test_a_malformed_line_is_refused_with_its_number(tmp_path, text, message):
    with pytest.raises(SettingsError, match=message):
        read_env_file(write(tmp_path, text), REPO)


@pytest.mark.parametrize("mode", [0o640, 0o604, 0o644, 0o660])
def test_a_file_anyone_else_can_read_is_refused(tmp_path, mode):
    with pytest.raises(SettingsError, match="chmod 600"):
        read_env_file(write(tmp_path, "NODE=a\n", mode), REPO)


def test_a_file_inside_the_repository_is_refused(tmp_path):
    inside = REPO / "scratch-run-test.env"
    inside.write_text("NODE=a\n")
    inside.chmod(0o600)
    try:
        with pytest.raises(SettingsError, match="outside the repository"):
            read_env_file(inside, REPO)
    finally:
        inside.unlink()


def test_a_missing_file_says_how_to_create_it(tmp_path):
    with pytest.raises(SettingsError, match="--init-env"):
        read_env_file(tmp_path / "absent.env", REPO)


def test_the_real_environment_beats_the_file():
    assert merge({"NODE": "from-env", "A": "1"}, {"NODE": "from-file", "B": "2"}) == {"NODE": "from-env", "A": "1", "B": "2"}


def test_init_writes_a_template_only_the_owner_can_read(tmp_path):
    path = init_env_file(tmp_path / "dir" / "scratch-run.env")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert "PROXMOX_API_TOKEN=" in path.read_text() and settings.OUT_DIR in path.read_text()


def test_the_template_is_valid_settings_that_still_need_filling_in(tmp_path):
    values = read_env_file(init_env_file(tmp_path / "scratch-run.env"), REPO)
    assert values["NODE"] == "root@pve" and settings.IMAGE_CHECKSUM not in values


def test_init_never_overwrites(tmp_path):
    path = write(tmp_path, "NODE=mine\n")
    with pytest.raises(SettingsError, match="already exists"):
        init_env_file(path)
    assert path.read_text() == "NODE=mine\n"


def test_the_file_is_owned_by_the_user_who_reads_it(tmp_path):
    assert write(tmp_path, "NODE=a\n").stat().st_uid == os.getuid()
