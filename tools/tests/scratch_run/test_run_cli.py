from __future__ import annotations

import tarfile
from pathlib import Path

import pytest
from scratch_run import __main__ as cli
from scratch_run.__main__ import main
from scratch_run.image_pin import ImagePinError, load_pin
from scratch_run_fakes import RUNS, FakeBackend, masters

SPEC = str(RUNS / "rehearsal.yaml")


@pytest.fixture(autouse=True)
def no_settings_of_the_developer(monkeypatch, tmp_path_factory):
    monkeypatch.setenv("HOME", str(tmp_path_factory.mktemp("home")))


def factory(backend, seen=None):
    def make(out, url, checksum, env):
        if seen is not None:
            seen.update(out=out, url=url, checksum=checksum, env=dict(env))
        return backend

    return make


def settings_file(tmp_path, text):
    path = tmp_path / "scratch-run.env"
    path.write_text(text)
    path.chmod(0o600)
    return path


def test_check_spec_reads_the_spec_and_needs_nothing_else(capsys):
    assert main([SPEC, "--check-spec"]) == 0
    assert capsys.readouterr().out == "rehearsal: 9 steps, valid\n"


def test_a_spec_is_found_by_its_name(capsys):
    assert main(["vlan-70-seed", "--check-spec"]) == 0
    assert capsys.readouterr().out == "vlan-70-seed: 5 steps, valid\n"


def test_an_unknown_name_lists_the_specs_there_are(capsys):
    assert main(["no-such-spec", "--check-spec"]) == 2
    assert f"the specs are: {', '.join(sorted(path.stem for path in RUNS.glob('*.yaml')))}" in capsys.readouterr().err


def test_list_shows_each_spec_with_what_it_shows(capsys):
    assert main(["--list"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert [line.split(":")[0] for line in lines] == sorted(path.stem for path in RUNS.glob("*.yaml"))
    assert all("NOT VALID" not in line for line in lines)


def test_a_bad_spec_exits_2_and_names_the_problems(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: Bad\n")
    assert main([str(bad), "--check-spec"]) == 2
    assert "`name` must be lowercase" in capsys.readouterr().err


def test_a_run_without_a_spec_is_refused(capsys):
    with pytest.raises(SystemExit) as stop:
        main([])
    assert stop.value.code == 2
    assert "a SPEC is needed" in capsys.readouterr().err


def test_a_run_needs_an_out_dir_from_somewhere(capsys):
    assert main([SPEC, "--preflight"], environ={}, backend_factory=factory(FakeBackend())) == 2
    assert "no OUT_DIR" in capsys.readouterr().err


def test_preflight_lists_the_problems_and_runs_nothing(tmp_path, capsys):
    backend = FakeBackend(problems=["NODE is not set"])
    assert main([SPEC, str(tmp_path / "out"), "--preflight"], environ={}, backend_factory=factory(backend)) == 2
    assert capsys.readouterr().out == "- NODE is not set\n"
    assert backend.calls == ["preflight"]


def test_preflight_with_nothing_missing_says_the_run_is_ready(tmp_path, capsys):
    assert main([SPEC, str(tmp_path / "out"), "--preflight"], environ={}, backend_factory=factory(FakeBackend())) == 0
    assert capsys.readouterr().out == "rehearsal: ready to run\n"


def test_the_settings_file_supplies_the_environment_the_image_and_the_out_dir(tmp_path):
    path = settings_file(
        tmp_path, f"NODE=root@pve\nSCRATCH_RUN_OUT_DIR={tmp_path / 'state'}\nSCRATCH_RUN_IMAGE_URL=https://x/a.img.bz2\nSCRATCH_RUN_IMAGE_CHECKSUM={'a' * 64}\n"
    )
    seen: dict = {}
    assert main(["rehearsal", "--preflight", "--env-file", str(path)], environ={}, backend_factory=factory(FakeBackend(), seen), master_factory=masters()) == 0
    assert (seen["out"].parent, seen["url"], seen["checksum"], seen["env"]["NODE"]) == (tmp_path / "state", "https://x/a.img.bz2", "a" * 64, "root@pve")
    assert seen["out"].name.startswith("state-rehearsal-")


def test_a_flag_beats_the_environment_and_the_environment_beats_the_file(tmp_path):
    path = settings_file(tmp_path, "NODE=from-file\nSCRATCH_RUN_IMAGE_URL=from-file\nSCRATCH_RUN_OUT_DIR=/from/file\n")
    seen: dict = {}
    argv = ["rehearsal", str(tmp_path / "flag-out"), "--preflight", "--env-file", str(path), "--image-url", "from-flag"]
    main(argv, environ={"NODE": "from-env"}, backend_factory=factory(FakeBackend(), seen), master_factory=masters())
    assert (seen["out"].parent, seen["url"], seen["env"]["NODE"]) == (tmp_path / "flag-out", "from-flag", "from-env")


def test_the_default_settings_file_is_used_when_it_exists(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".config/homelab").mkdir(parents=True)
    settings_file(home / ".config/homelab", "NODE=from-default\nSCRATCH_RUN_OUT_DIR=~/state\n").rename(home / ".config/homelab/scratch-run.env")
    monkeypatch.setenv("HOME", str(home))
    seen: dict = {}
    assert main(["rehearsal", "--preflight"], environ={}, backend_factory=factory(FakeBackend(), seen), master_factory=masters()) == 0
    assert (seen["env"]["NODE"], seen["out"].parent) == ("from-default", home / "state")


def test_an_env_file_that_is_named_and_missing_is_an_error(tmp_path, capsys):
    assert main(["rehearsal", "--preflight", "--env-file", str(tmp_path / "absent.env")], environ={}, backend_factory=factory(FakeBackend())) == 2
    assert "--init-env" in capsys.readouterr().err


def test_an_unsafe_settings_file_stops_the_run(tmp_path, capsys):
    path = settings_file(tmp_path, "NODE=a\n")
    path.chmod(0o644)
    assert main(["rehearsal", "--preflight", "--env-file", str(path)], environ={}, backend_factory=factory(FakeBackend())) == 2
    assert "chmod 600" in capsys.readouterr().err


def test_init_env_writes_the_settings_file_and_says_what_to_do_next(tmp_path, capsys):
    target = tmp_path / "new" / "scratch-run.env"
    assert main(["--init-env", "--env-file", str(target)]) == 0
    assert target.is_file() and "fill it in" in capsys.readouterr().out
    assert main(["--init-env", "--env-file", str(target)]) == 2


def test_a_run_bundles_its_results_in_the_out_dir(tmp_path, capsys):
    backend = FakeBackend()
    assert main([SPEC, str(tmp_path / "out"), "--keep"], environ={}, backend_factory=factory(backend)) == 0
    archives = list((tmp_path / "out").glob("results-rehearsal-*.tgz"))
    assert len(archives) == 1 and "down" not in backend.calls
    with tarfile.open(archives[0]) as tar:
        assert any(name.endswith("/results.md") for name in tar.getnames())
    assert "ALL STEPS PASSED" in capsys.readouterr().out


def run_with_node(tmp_path, made, **options):
    seen: dict = {}
    status = main(
        ["rehearsal", str(tmp_path / "out"), "--preflight"],
        environ={"NODE": "root@pve"},
        backend_factory=factory(FakeBackend(), seen),
        master_factory=masters(made, **options),
    )
    return status, seen


def test_the_ssh_master_is_opened_before_the_run_and_its_default_socket_reaches_the_backend(tmp_path):
    made: list = []
    status, seen = run_with_node(tmp_path, made)
    assert status == 0 and made[0].asked == ["ensure"]
    assert seen["env"]["SSH_CONTROL_PATH"] == str(Path("~/.cache/scratch-run/ssh.sock").expanduser()) == str(made[0].socket)


def test_a_socket_from_the_settings_is_used(tmp_path):
    made: list = []
    main(
        ["rehearsal", str(tmp_path / "out"), "--preflight"],
        environ={"NODE": "n", "SSH_CONTROL_PATH": "/tmp/mine.sock"},
        backend_factory=factory(FakeBackend()),
        master_factory=masters(made),
    )
    assert made[0].socket == Path("/tmp/mine.sock")


def test_a_master_that_cannot_be_opened_stops_the_run_with_the_reason(tmp_path, capsys):
    backend = FakeBackend()
    status = main(
        ["rehearsal", str(tmp_path / "out")],
        environ={"NODE": "n"},
        backend_factory=factory(backend),
        master_factory=masters(problem="ssh to n failed (exit 255)"),
    )
    assert status == 2 and "ssh to n failed (exit 255)" in capsys.readouterr().err
    assert backend.calls == []


def test_without_a_node_no_master_is_made(tmp_path):
    made: list = []
    main(["rehearsal", str(tmp_path / "out"), "--preflight"], environ={}, backend_factory=factory(FakeBackend()), master_factory=masters(made))
    assert made == []


def test_ssh_up_opens_the_master(capsys):
    made: list = []
    assert main(["--ssh", "up"], environ={"NODE": "n"}, master_factory=masters(made)) == 0
    assert made[0].asked == ["ensure"] and "ssh master to n is up at" in capsys.readouterr().out


def test_ssh_up_that_fails_says_why(capsys):
    assert main(["--ssh", "up"], environ={"NODE": "n"}, master_factory=masters(problem="no way in")) == 2
    assert "no way in" in capsys.readouterr().err


@pytest.mark.parametrize(("up", "status", "word"), [(True, 0, "up"), (False, 1, "down")])
def test_ssh_status_exits_0_only_when_the_master_is_up(up, status, word, capsys):
    assert main(["--ssh", "status"], environ={"NODE": "n"}, master_factory=masters(up=up)) == status
    assert f"is {word} (" in capsys.readouterr().out


@pytest.mark.parametrize(("up", "said"), [(True, "is closed"), (False, "was not up")])
def test_ssh_down_closes_the_master_if_there_is_one(up, said, capsys):
    assert main(["--ssh", "down"], environ={"NODE": "n"}, master_factory=masters(up=up)) == 0
    assert said in capsys.readouterr().out


def test_ssh_needs_a_node(capsys):
    assert main(["--ssh", "up"], environ={}, master_factory=masters()) == 2
    assert "NODE is not set" in capsys.readouterr().err


def test_the_qemu_backend_boots_the_pinned_image_when_none_is_given(tmp_path):

    seen: dict = {}
    assert main(["rehearsal", str(tmp_path / "out"), "--preflight", "--backend", "qemu"], environ={}, backend_factory=factory(FakeBackend(), seen)) == 0
    assert (seen["url"], seen["checksum"]) == (load_pin().url, load_pin().sha256)


def test_an_image_from_a_flag_beats_the_pin_for_the_qemu_backend(tmp_path):
    seen: dict = {}
    argv = ["rehearsal", str(tmp_path / "out"), "--preflight", "--backend", "qemu", "--image-url", "u", "--image-checksum", "c"]
    main(argv, environ={}, backend_factory=factory(FakeBackend(), seen))
    assert (seen["url"], seen["checksum"]) == ("u", "c")


def test_the_node_backend_does_not_read_the_pin(tmp_path):
    seen: dict = {}
    main(["rehearsal", str(tmp_path / "out"), "--preflight"], environ={}, backend_factory=factory(FakeBackend(), seen))
    assert (seen["url"], seen["checksum"]) == ("", "")


def test_a_broken_pin_stops_a_qemu_run_before_the_backend_is_made(tmp_path, monkeypatch, capsys):

    def broken():
        raise ImagePinError("image-pin.yaml cannot be read")

    monkeypatch.setattr(cli, "load_pin", broken)
    backend = FakeBackend()
    assert main(["rehearsal", str(tmp_path / "out"), "--backend", "qemu"], environ={}, backend_factory=factory(backend)) == 2
    assert "cannot be read" in capsys.readouterr().err and backend.calls == []


def test_a_node_in_the_environment_opens_no_master_for_the_qemu_backend(tmp_path):
    made: list = []
    main(
        ["rehearsal", str(tmp_path / "out"), "--preflight", "--backend", "qemu"],
        environ={"NODE": "n"},
        backend_factory=factory(FakeBackend()),
        master_factory=masters(made),
    )
    assert made == []


def test_an_unknown_backend_is_refused(tmp_path):
    with pytest.raises(SystemExit) as stop:
        main(["rehearsal", str(tmp_path / "out"), "--backend", "docker"], environ={})
    assert stop.value.code == 2
