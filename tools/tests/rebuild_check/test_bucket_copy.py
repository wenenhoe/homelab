"""Unit tests for rebuild_check/scripts/bucket_copy.py. docker is replaced by a recorder; nothing here reaches a host."""

from __future__ import annotations

import importlib.util
import json
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "rebuild_check/scripts/bucket_copy.py"
_spec = importlib.util.spec_from_file_location("bucket_copy", SCRIPT)
bucket_copy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bucket_copy)

IMAGE = "rclone/rclone:1.75@sha256:" + "a" * 64
UNIT = f"ExecStart=/usr/bin/docker run --rm \\\n  {IMAGE} \\\n  /run.sh\n"
CONF = """[seaweedfs]
type = s3
access_key_id = READER_AK
secret_access_key = READER_SK
endpoint = https://s3.store.lan.example.com

[r2]
type = s3
access_key_id = R2_AK
secret_access_key = R2_SK
endpoint = https://acct.r2.example.com
region = auto
"""
IDENTITIES = json.dumps(
    {
        "identities": [
            {"name": "seaweedfs-cloud-sync-reader", "credentials": [{"accessKey": "READER_AK", "secretKey": "READER_SK"}]},
            {"name": "seaweedfs-bucket-admin", "credentials": [{"accessKey": "ADMIN_AK", "secretKey": "ADMIN_SK"}]},
        ]
    }
)
SECRETS = ("READER_SK", "ADMIN_SK", "R2_SK")


class Docker:
    """Records every command; reads the env file at the moment docker run would, since the tool removes it afterwards."""

    def __init__(self, fail_on: str | None = None, identity_status: int = 0):
        self.calls: list[list[str]] = []
        self.env_seen: list[dict[str, str]] = []
        self.modes: list[int] = []
        self.env_paths: list[Path] = []
        self.fail_on = fail_on
        self.identity_status = identity_status

    def __call__(self, argv, **_kwargs):
        self.calls.append(argv)
        if argv[:3] == ["docker", "exec", "seaweedfs"]:
            return subprocess.CompletedProcess(argv, self.identity_status, stdout=IDENTITIES, stderr="")
        env_file = Path(argv[argv.index("--env-file") + 1])
        self.env_paths.append(env_file)
        self.modes.append(stat.S_IMODE(env_file.stat().st_mode))
        self.env_seen.append(dict(line.split("=", 1) for line in env_file.read_text().splitlines()))
        failed = self.fail_on is not None and self.fail_on in argv
        return subprocess.CompletedProcess(argv, 3 if failed else 0)

    def rclone_commands(self) -> list[str]:
        out = []
        for argv in self.calls:
            if "--config" in argv:
                out.append(" ".join(argv[argv.index("/dev/null") + 1 :]))
        return out


@pytest.fixture
def host(tmp_path, monkeypatch):
    unit, conf = tmp_path / "cloud-sync.service", tmp_path / "rclone.conf"
    unit.write_text(UNIT)
    conf.write_text(CONF)
    monkeypatch.setattr(bucket_copy, "SERVICE_UNIT", unit)
    monkeypatch.setattr(bucket_copy, "RCLONE_CONF", conf)
    return tmp_path


class TestParts:
    def test_the_image_is_the_one_the_unit_pins(self):
        assert bucket_copy.cloud_sync_image(UNIT) == IMAGE

    def test_a_unit_without_a_pinned_image_is_an_error(self):
        with pytest.raises(bucket_copy.CopyError, match="no pinned rclone image"):
            bucket_copy.cloud_sync_image("ExecStart=/bin/true\n")

    def test_the_source_remote_is_a_section_of_the_conf(self):
        remote = bucket_copy.source_remote(CONF, "r2")
        assert (remote["access_key_id"], remote["endpoint"], remote["region"]) == ("R2_AK", "https://acct.r2.example.com", "auto")

    def test_a_section_the_conf_lacks_is_an_error_that_lists_what_it_has(self):
        with pytest.raises(bucket_copy.CopyError, match=r"no \[b2\].*seaweedfs, r2"):
            bucket_copy.source_remote(CONF, "b2")

    def test_the_admin_identity_is_found_by_name_not_position(self):
        assert bucket_copy.admin_remote(IDENTITIES) == {"access_key_id": "ADMIN_AK", "secret_access_key": "ADMIN_SK", "endpoint": "http://seaweedfs:8333"}

    @pytest.mark.parametrize("text", ["not json", "{}", json.dumps({"identities": [{"name": "other", "credentials": []}]})])
    def test_an_identity_file_without_the_admin_is_an_error(self, text):
        with pytest.raises(bucket_copy.CopyError):
            bucket_copy.admin_remote(text)

    def test_the_env_form_of_a_remote_sets_type_provider_and_path_style(self):
        env = bucket_copy.remote_env("old", {"access_key_id": "A", "secret_access_key": "S", "endpoint": "https://e"})
        assert env == {
            "RCLONE_CONFIG_OLD_TYPE": "s3",
            "RCLONE_CONFIG_OLD_PROVIDER": "Other",
            "RCLONE_CONFIG_OLD_FORCE_PATH_STYLE": "true",
            "RCLONE_CONFIG_OLD_ACCESS_KEY_ID": "A",
            "RCLONE_CONFIG_OLD_SECRET_ACCESS_KEY": "S",
            "RCLONE_CONFIG_OLD_ENDPOINT": "https://e",
        }

    def test_a_pin_needs_a_name_to_pin(self):
        assert bucket_copy.pin_argument("https://s3.store.lan.example.com:443", "192.168.20.6") == ["--add-host", "s3.store.lan.example.com:192.168.20.6"]
        with pytest.raises(bucket_copy.CopyError, match="needs a source endpoint with a name"):
            bucket_copy.pin_argument("https://192.168.20.6", "192.168.20.6")


class TestCopy:
    @pytest.mark.usefixtures("host")
    def test_copies_immutably_then_sizes_both_sides_then_checks_size_only(self, capsys):
        docker = Docker()
        assert bucket_copy.main(["--pin", "192.168.20.7"], run=docker) == 0
        assert docker.rclone_commands() == [
            "copy --immutable --stats-one-line -v old:homelab-backups new:homelab-backups",
            "size old:homelab-backups",
            "size new:homelab-backups",
            "check --size-only old:homelab-backups new:homelab-backups",
        ]
        assert "the copy and the source hold the same files" in capsys.readouterr().out

    @pytest.mark.usefixtures("host")
    def test_each_container_is_hardened_on_the_caddy_network_with_the_source_name_pinned(self):
        docker = Docker()
        bucket_copy.main(["--pin", "192.168.20.7"], run=docker)
        argv = docker.calls[1]
        assert argv[:5] == ["docker", "run", "--rm", "--network", "caddy-proxy"]
        pinned = ["--add-host", "s3.store.lan.example.com:192.168.20.7"]
        for flag in (["--cap-drop", "ALL"], ["--security-opt", "no-new-privileges:true"], ["--read-only"], pinned):
            assert " ".join(flag) in " ".join(argv)
        assert IMAGE in argv

    @pytest.mark.usefixtures("host")
    def test_the_remotes_are_the_reader_at_the_clients_name_and_the_admin_at_the_local_endpoint(self):
        docker = Docker()
        bucket_copy.main([], run=docker)
        env = docker.env_seen[0]
        assert (env["RCLONE_CONFIG_OLD_ACCESS_KEY_ID"], env["RCLONE_CONFIG_OLD_ENDPOINT"]) == ("READER_AK", "https://s3.store.lan.example.com")
        assert (env["RCLONE_CONFIG_NEW_ACCESS_KEY_ID"], env["RCLONE_CONFIG_NEW_ENDPOINT"]) == ("ADMIN_AK", "http://seaweedfs:8333")

    @pytest.mark.usefixtures("host")
    def test_no_pin_means_no_add_host(self):
        docker = Docker()
        bucket_copy.main([], run=docker)
        assert all("--add-host" not in argv for argv in docker.calls)

    @pytest.mark.usefixtures("host")
    def test_a_cloud_target_can_be_the_source_for_a_restore_to_storage(self):
        docker = Docker()
        bucket_copy.main(["--from", "r2", "--bucket", "r2-bucket"], run=docker)
        env = docker.env_seen[0]
        assert (env["RCLONE_CONFIG_OLD_ACCESS_KEY_ID"], env["RCLONE_CONFIG_OLD_REGION"]) == ("R2_AK", "auto")
        assert docker.rclone_commands()[0] == "copy --immutable --stats-one-line -v old:r2-bucket new:r2-bucket"

    @pytest.mark.usefixtures("host")
    def test_check_only_copies_nothing(self):
        docker = Docker()
        assert bucket_copy.main(["--check-only"], run=docker) == 0
        assert not any(command.startswith("copy") for command in docker.rclone_commands())
        assert docker.rclone_commands()[-1].startswith("check --size-only")

    @pytest.mark.usefixtures("host")
    def test_a_difference_in_the_check_is_the_exit_status(self, capsys):
        assert bucket_copy.main([], run=Docker(fail_on="check")) == 3
        assert "check failed (exit 3)" in capsys.readouterr().err

    @pytest.mark.usefixtures("host")
    def test_a_failed_copy_stops_before_the_sizes_and_the_check(self):
        docker = Docker(fail_on="copy")
        assert bucket_copy.main([], run=docker) == 3
        assert len(docker.rclone_commands()) == 1


class TestSecrets:
    @pytest.mark.usefixtures("host")
    def test_the_env_file_is_private_while_it_exists_and_gone_afterwards(self):
        docker = Docker()
        bucket_copy.main([], run=docker)
        assert set(docker.modes) == {0o600}
        assert not any(path.exists() for path in docker.env_paths)

    @pytest.mark.usefixtures("host")
    def test_the_env_file_is_gone_after_a_failed_step_too(self):
        docker = Docker(fail_on="check")
        bucket_copy.main([], run=docker)
        assert not any(path.exists() for path in docker.env_paths)

    @pytest.mark.usefixtures("host")
    def test_no_secret_reaches_a_command_line_or_the_output(self, capsys):
        docker = Docker(fail_on="check")
        bucket_copy.main(["--pin", "192.168.20.7"], run=docker)
        text = capsys.readouterr()
        everything = " ".join(" ".join(argv) for argv in docker.calls) + text.out + text.err
        assert not any(secret in everything for secret in SECRETS)


class TestRefusals:
    @pytest.mark.usefixtures("host")
    def test_a_seaweedfs_that_is_not_running_says_so_and_runs_no_rclone(self, capsys):
        docker = Docker(identity_status=1)
        assert bucket_copy.main([], run=docker) == 1
        assert "is it running?" in capsys.readouterr().err
        assert docker.rclone_commands() == []

    @pytest.mark.usefixtures("host")
    def test_an_unknown_source_remote_is_refused_before_docker_is_asked_anything(self, capsys):
        docker = Docker()
        assert bucket_copy.main(["--from", "b2"], run=docker) == 1
        assert "no [b2]" in capsys.readouterr().err
        assert docker.calls == []
