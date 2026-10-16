"""Tests for container_hardening.scan_image, against archives built in the test.

`_image_tars.write_image` writes the same archive shape `docker save` does, so
the layer, whiteout, xattr and script handling run without Docker. The three
Docker calls are replaced at the module's own functions.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import subprocess
import tarfile
from typing import ClassVar
from unittest.mock import create_autospec

import pytest
from _image_tars import capability_xattr, directory_entry, file_entry, opaque, whiteout, write_image
from container_hardening import scan_image as si

NET_BIND_SERVICE = 1 << 10
NET_RAW = 1 << 13
SETUID_MODE = 0o4755
SETGID_MODE = 0o2755


def _xattr_bytes(value: str) -> bytes:
    return value.encode("utf-8", "surrogateescape")


class TestDecodeCapability:
    @pytest.mark.parametrize(
        ("revision", "effective", "permitted", "names"),
        [
            pytest.param(2, True, NET_BIND_SERVICE, ["NET_BIND_SERVICE"], id="v2-effective"),
            pytest.param(2, False, NET_RAW, ["NET_RAW"], id="v2-not-effective"),
            pytest.param(1, True, NET_BIND_SERVICE | NET_RAW, ["NET_BIND_SERVICE", "NET_RAW"], id="v1-one-word"),
            pytest.param(3, True, 1 << 38, ["PERFMON"], id="v3-high-word"),
        ],
    )
    def test_names_the_permitted_set_and_the_effective_bit(self, revision, effective, permitted, names):
        value = _xattr_bytes(capability_xattr(permitted, effective=effective, revision=revision))

        decoded = si.decode_capability(value)

        assert decoded == {"effective_bit": effective, "permitted": names, "inheritable": []}

    def test_inheritable_set_is_decoded_apart_from_permitted(self):
        value = _xattr_bytes(capability_xattr(NET_RAW, inheritable=NET_BIND_SERVICE))

        decoded = si.decode_capability(value)

        assert (decoded["permitted"], decoded["inheritable"]) == (["NET_RAW"], ["NET_BIND_SERVICE"])


class TestCollectFiles:
    def test_reads_mode_capability_and_script_text(self, tmp_path):
        cap = capability_xattr(NET_BIND_SERVICE)
        image = write_image(
            tmp_path / "i.tar",
            [[file_entry("./usr/bin/server", b"\x7fELF", 0o755, cap), file_entry("./entrypoint.sh", b'#!/bin/sh\nexec gosu app "$@"\n', 0o755)]],
        )

        files = si.collect_files(image)

        assert files["/usr/bin/server"] == (0o755, cap, None)
        assert files["/entrypoint.sh"][2] == '#!/bin/sh\nexec gosu app "$@"\n'

    def test_keeps_the_leading_dot_of_a_hidden_file(self, tmp_path):
        image = write_image(tmp_path / "i.tar", [[file_entry("./.hidden/run.sh", b"#!/bin/sh\n", 0o755)]])

        assert list(si.collect_files(image)) == ["/.hidden/run.sh"]

    def test_a_non_script_executable_is_not_read_as_text(self, tmp_path):
        image = write_image(tmp_path / "i.tar", [[file_entry("bin/tool", b"not a script", 0o755)]])

        assert si.collect_files(image)["/bin/tool"][2] is None

    def test_a_later_layer_replaces_a_file(self, tmp_path):
        image = write_image(tmp_path / "i.tar", [[file_entry("bin/su", mode=SETUID_MODE)], [file_entry("bin/su", mode=0o755)]])

        assert si.collect_files(image)["/bin/su"][0] == 0o755

    def test_a_whiteout_removes_the_file_and_a_directory_tree(self, tmp_path):
        image = write_image(
            tmp_path / "i.tar",
            [
                [file_entry("bin/su", mode=SETUID_MODE), file_entry("opt/app/a"), file_entry("opt/app/deep/b"), file_entry("opt/keep")],
                [whiteout("bin/su"), whiteout("opt/app")],
            ],
        )

        assert sorted(si.collect_files(image)) == ["/opt/keep"]

    def test_an_opaque_whiteout_clears_lower_files_in_that_directory_only(self, tmp_path):
        image = write_image(
            tmp_path / "i.tar",
            [[file_entry("etc/old"), file_entry("etc/sub/old"), file_entry("var/other")], [opaque("etc"), file_entry("etc/new")]],
        )

        assert sorted(si.collect_files(image)) == ["/etc/new", "/var/other"]

    def test_a_directory_over_a_file_drops_the_file(self, tmp_path):
        image = write_image(tmp_path / "i.tar", [[file_entry("srv/x", mode=SETUID_MODE)], [directory_entry("srv/x")]])

        assert si.collect_files(image) == {}


class TestFindings:
    CONFIG: ClassVar[dict] = {"User": "1000", "Entrypoint": ["/entrypoint.sh"], "Cmd": ["run"]}

    def test_reports_setuid_setgid_and_file_capabilities(self):
        cap = capability_xattr(NET_BIND_SERVICE)
        files = {"/bin/su": (SETUID_MODE, None, None), "/bin/wall": (SETGID_MODE, None, None), "/usr/bin/step-ca": (0o755, cap, None)}

        result = si.findings("img", self.CONFIG, files)

        assert (result["setuid"], result["setgid"]) == (["/bin/su"], ["/bin/wall"])
        assert result["filecaps"] == [{"path": "/usr/bin/step-ca", "effective_bit": True, "permitted": ["NET_BIND_SERVICE"], "inheritable": []}]

    def test_an_image_without_a_user_runs_as_root(self):
        assert si.findings("img", {"User": ""}, {})["user"] == "root"
        assert si.findings("img", {}, {})["user"] == "root"

    def test_copies_entrypoint_and_cmd_from_the_config(self):
        result = si.findings("img", self.CONFIG, {})

        assert (result["entrypoint"], result["cmd"]) == (["/entrypoint.sh"], ["run"])

    def test_flags_a_helper_call_with_its_file_and_line(self):
        script = '#!/bin/sh\nset -e\nchown -R app /data\nexec su-exec app "$@"\n'

        result = si.findings("img", self.CONFIG, {"/entrypoint.sh": (0o755, None, script)})

        assert result["helpers"] == ["/entrypoint.sh:3: chown -R app /data", '/entrypoint.sh:4: exec su-exec app "$@"']

    def test_ignores_a_helper_named_only_in_a_comment(self):
        script = "#!/bin/sh\n# we used to gosu here\n  # chown is no longer needed\nexec app\n"

        assert si.findings("img", self.CONFIG, {"/entrypoint.sh": (0o755, None, script)})["helpers"] == []

    @pytest.mark.parametrize("line", ["su - app -c run", "su app -c run"], ids=["su-dash", "su-user"])
    def test_flags_su_followed_by_a_user(self, line):
        assert len(si.findings("img", self.CONFIG, {"/e.sh": (0o755, None, f"#!/bin/sh\n{line}\n")})["helpers"]) == 1

    def test_a_word_that_only_contains_a_helper_name_is_not_flagged(self):
        script = "#!/bin/sh\necho result sudoku chowned\n"

        assert si.findings("img", self.CONFIG, {"/e.sh": (0o755, None, script)})["helpers"] == []


class TestScan:
    def test_combines_the_docker_config_with_the_saved_archive(self, tmp_path, monkeypatch):
        archive = write_image(tmp_path / "source.tar", [[file_entry("bin/su", mode=SETUID_MODE)]])

        def save(image, destination):
            destination.write_bytes(archive.read_bytes())

        monkeypatch.setattr(si, "docker_config", create_autospec(si.docker_config, return_value={"User": "app"}))
        saver = create_autospec(si.docker_save, side_effect=save)
        monkeypatch.setattr(si, "docker_save", saver)

        result = si.scan("example/img:1")

        assert (result["image"], result["user"], result["setuid"]) == ("example/img:1", "app", ["/bin/su"])
        assert saver.call_args.args[0] == "example/img:1"


class TestReport:
    def _result(self, **changes):
        base = {"image": "img", "user": "root", "entrypoint": None, "cmd": None, "setuid": [], "setgid": [], "filecaps": [], "helpers": []}
        return base | changes

    def test_a_clean_image_says_none_for_each_check(self):
        text = si.report(self._result())

        assert "=== img" in text
        assert "setuid/setgid binaries): none" in text
        assert "file capabilities: none" in text
        assert "helpers in shell scripts: none found" in text

    def test_lists_blockers_capabilities_and_helpers(self):
        cap = {"path": "/usr/bin/step-ca", "permitted": ["NET_BIND_SERVICE"], "effective_bit": True, "inheritable": []}
        text = si.report(self._result(setuid=["/bin/su"], setgid=["/bin/wall"], filecaps=[cap], helpers=["/e.sh:2: gosu app"]))

        assert "setuid/setgid binaries): /bin/su, /bin/wall" in text
        assert "file capability: /usr/bin/step-ca permitted=['NET_BIND_SERVICE'] effective_bit=True  -> cap_drop ALL breaks it unless re-added" in text
        assert "    /e.sh:2: gosu app" in text

    def test_caps_the_helper_list(self):
        helpers = [f"/e.sh:{number}: gosu app" for number in range(1, 40)]

        text = si.report(self._result(helpers=helpers))

        assert text.count("gosu app") == si.MAX_HELPER_LINES


class TestMain:
    def test_no_arguments_prints_the_usage_and_exits_2(self, capsys):
        code = si.main([])

        assert code == 2
        assert "python -m container_hardening.scan_image IMAGE" in capsys.readouterr().out

    def test_running_scans_every_running_image(self, monkeypatch, capsys):
        monkeypatch.setattr(si, "running_images", create_autospec(si.running_images, return_value=["a:1", "b:2"]))
        scanner = create_autospec(si.scan, side_effect=lambda image: TestReport()._result(image=image))
        monkeypatch.setattr(si, "scan", scanner)

        code = si.main(["--running"])

        assert code == 0
        assert [call.args[0] for call in scanner.call_args_list] == ["a:1", "b:2"]
        assert "=== a:1" in capsys.readouterr().out

    @pytest.mark.parametrize(
        "error",
        [subprocess.CalledProcessError(1, "docker"), OSError("no docker"), tarfile.ReadError("bad archive"), KeyError("manifest.json")],
        ids=["docker-failed", "no-docker", "bad-archive", "no-manifest"],
    )
    def test_a_failed_image_is_reported_and_the_next_one_still_scans(self, monkeypatch, capsys, error):
        def scan(image):
            if image == "bad:1":
                raise error
            return TestReport()._result(image=image)

        monkeypatch.setattr(si, "scan", create_autospec(si.scan, side_effect=scan))

        code = si.main(["bad:1", "good:1"])

        out = capsys.readouterr().out
        assert code == 1
        assert "=== bad:1\n  scan failed:" in out
        assert "=== good:1" in out
