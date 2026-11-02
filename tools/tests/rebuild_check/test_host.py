"""Unit tests for rebuild_check.host. Every command's output is canned; nothing here reaches a real host."""

from __future__ import annotations

from unittest.mock import create_autospec

import pytest
from _ssh_objects import exec_result
from rebuild_check import host

EXPECTED = host.Expected(
    host="security",
    address="192.168.20.5",
    fqdn="security.internal.example.com",
    timezone="Asia/Singapore",
    probe_image="alpine:3.24@sha256:" + "a" * 64,
)

IP_STATIC = "2: eth0    inet 192.168.20.5/24 brd 192.168.20.255 scope global eth0\\       valid_lft forever preferred_lft forever\n"
IP_DHCP = "2: eth0    inet 192.168.20.5/24 metric 100 brd 192.168.20.255 scope global dynamic eth0\\       valid_lft 3000sec preferred_lft 3000sec\n"


def runner(outputs: dict[str, tuple[int, str]]):
    """A runner that answers only the commands a test names: an unexpected command fails the test."""
    calls: list[str] = []

    def run(command: str) -> tuple[int, str]:
        calls.append(command)
        return outputs[command]

    run.calls = calls
    return run


class TestAddress:
    def test_a_static_address_passes(self):
        assert host.address_is_static(runner({"ip -4 -o addr show scope global": (0, IP_STATIC)}), EXPECTED).ok

    def test_a_dhcp_lease_fails_and_says_so(self):
        result = host.address_is_static(runner({"ip -4 -o addr show scope global": (0, IP_DHCP)}), EXPECTED)
        assert (result.ok, "DHCP lease" in result.detail) == (False, True)

    def test_another_address_fails(self):
        result = host.address_is_static(runner({"ip -4 -o addr show scope global": (0, IP_STATIC.replace("192.168.20.5", "192.168.20.9"))}), EXPECTED)
        assert not result.ok
        assert "192.168.20.9" in result.detail


class TestDracutNetworkFile:
    def test_the_file_fails_the_check(self):
        out = "10-netplan-eth0.network\nzzzz-dracut-default.network\n"
        assert not host.no_dracut_network_file(runner({"ls /run/systemd/network": (0, out)}), EXPECTED).ok

    def test_netplans_files_alone_pass(self):
        assert host.no_dracut_network_file(runner({"ls /run/systemd/network": (0, "10-netplan-eth0.link\n10-netplan-eth0.network\n")}), EXPECTED).ok


class TestNameResolution:
    def test_the_host_resolving_its_name_to_loopback_fails(self):
        run = runner({f"getent hosts {EXPECTED.fqdn}": (0, "127.0.1.1       security.internal.example.com security\n")})
        result = host.own_name_resolves_to_its_address(run, EXPECTED)
        assert (result.ok, "127.0.1.1" in result.detail) == (False, True)

    def test_the_right_address_passes(self):
        assert host.own_name_resolves_to_its_address(
            runner({f"getent hosts {EXPECTED.fqdn}": (0, "192.168.20.5  security.internal.example.com\n")}), EXPECTED
        ).ok

    def test_a_container_resolving_the_name_to_loopback_fails(self):
        command = f"docker run --rm --network caddy-proxy {EXPECTED.probe_image} getent hosts {EXPECTED.fqdn}"
        result = host.containers_resolve_the_hosts_name(runner({command: (0, "127.0.1.1  security.internal.example.com\n")}), EXPECTED)
        assert (result.ok, "caddy-proxy" in result.detail) == (False, True)

    def test_a_container_resolving_it_correctly_passes(self):
        command = f"docker run --rm --network caddy-proxy {EXPECTED.probe_image} getent hosts {EXPECTED.fqdn}"
        assert host.containers_resolve_the_hosts_name(runner({command: (0, "192.168.20.5  security.internal.example.com\n")}), EXPECTED).ok

    def test_a_name_that_does_not_resolve_fails_rather_than_passing_on_empty_output(self):
        assert not host.own_name_resolves_to_its_address(runner({f"getent hosts {EXPECTED.fqdn}": (2, "")}), EXPECTED).ok


class TestTimezoneAndUnits:
    @pytest.mark.parametrize(("output", "ok"), [pytest.param("Asia/Singapore\n", True, id="match"), pytest.param("UTC\n", False, id="utc")])
    def test_the_timezone_is_compared_with_the_inventorys(self, output, ok):
        assert host.timezone_is_the_inventorys(runner({"timedatectl show --property=Timezone --value": (0, output)}), EXPECTED).ok is ok

    def test_a_failed_unit_fails_the_check_and_is_named(self):
        result = host.no_failed_units(runner({"systemctl --failed --no-legend --plain": (0, "cloud-sync.service loaded failed failed Cloud sync\n")}), EXPECTED)
        assert (result.ok, "cloud-sync.service" in result.detail) == (False, True)

    def test_no_failed_units_passes(self):
        assert host.no_failed_units(runner({"systemctl --failed --no-legend --plain": (0, "")}), EXPECTED).ok


class TestContainers:
    COMMAND = "docker ps -a --format '{{.Names}}|{{.State}}|{{.Status}}'"

    @pytest.mark.parametrize(
        "line",
        [
            pytest.param("tinyauth|exited|Exited (1) 2 minutes ago", id="exited"),
            pytest.param("lldap|running|Up 3 minutes (unhealthy)", id="unhealthy"),
            pytest.param("caddy|running|Up 5 seconds (health: starting)", id="still-starting"),
            pytest.param("gatus|restarting|Restarting (1) 4 seconds ago", id="restarting"),
        ],
    )
    def test_a_container_that_is_not_settled_fails_and_is_named(self, line):
        result = host.containers_are_running_and_healthy(runner({self.COMMAND: (0, "step-ca|running|Up 2 hours (healthy)\n" + line + "\n")}), EXPECTED)
        assert (result.ok, line.split("|")[0] in result.detail) == (False, True)

    def test_openbao_reporting_unhealthy_is_not_this_checks_business(self):
        out = "openbao|running|Up 1 minute (unhealthy)\nstep-ca|running|Up 2 hours (healthy)\n"
        assert host.containers_are_running_and_healthy(runner({self.COMMAND: (0, out)}), EXPECTED).ok

    def test_healthy_containers_and_ones_without_a_healthcheck_pass(self):
        assert host.containers_are_running_and_healthy(
            runner({self.COMMAND: (0, "step-ca|running|Up 2 hours (healthy)\nbeszel-agent|running|Up 2 hours\n")}), EXPECTED
        ).ok


class TestSecurityChecks:
    @pytest.mark.parametrize(("status", "ok", "word"), [(0, True, "unsealed"), (2, False, "sealed"), (1, False, "failed")])
    def test_openbao_status_exit_codes(self, status, ok, word):
        result = host.openbao_is_unsealed(runner({"docker exec openbao bao status -address=https://127.0.0.1:8200": (status, "")}), EXPECTED)
        assert (result.ok, word in result.detail) == (ok, True)

    def test_step_ca_must_say_ok(self):
        command = "docker exec step-ca step ca health"
        assert host.step_ca_is_healthy(runner({command: (0, "ok\n")}), EXPECTED).ok
        assert not host.step_ca_is_healthy(runner({command: (1, "connection refused\n")}), EXPECTED).ok

    @pytest.mark.parametrize(
        ("status", "output", "ok"),
        [(0, "active\nactive\n", True), (3, "inactive\nactive\n", False), (3, "inactive\ninactive\n", False), (4, "", False)],
    )
    def test_the_watcher_and_its_timer_must_both_be_active(self, status, output, ok):
        command = "systemctl is-active r2-read-watcher.service r2-read-watcher-heartbeat.timer"
        assert host.r2_read_watcher_is_running(runner({command: (status, output)}), EXPECTED).ok is ok

    @pytest.mark.parametrize(("count", "ok"), [("0", True), ("4", False)])
    def test_tinyauth_ldap_errors_in_its_log(self, count, ok):
        command = "docker logs --since 10m tinyauth 2>&1 | grep -ciE 'ldap.*(error|failed)' || true"
        assert host.tinyauth_reaches_ldap(runner({command: (0, count + "\n")}), EXPECTED).ok is ok


class TestRunChecks:
    @staticmethod
    def _everything_passes(expected: host.Expected):
        outputs = {
            "ip -4 -o addr show scope global": (0, IP_STATIC),
            "ls /run/systemd/network": (0, "10-netplan-eth0.network\n"),
            f"getent hosts {expected.fqdn}": (0, f"{expected.address}  {expected.fqdn}\n"),
            f"docker run --rm --network caddy-proxy {expected.probe_image} getent hosts {expected.fqdn}": (0, f"{expected.address}  {expected.fqdn}\n"),
            "timedatectl show --property=Timezone --value": (0, expected.timezone + "\n"),
            "systemctl --failed --no-legend --plain": (0, ""),
            "docker ps -a --format '{{.Names}}|{{.State}}|{{.Status}}'": (0, "step-ca|running|Up 2 hours (healthy)\n"),
            "docker exec openbao bao status -address=https://127.0.0.1:8200": (0, ""),
            "docker exec step-ca step ca health": (0, "ok\n"),
            "systemctl is-active r2-read-watcher.service r2-read-watcher-heartbeat.timer": (0, "active\nactive\n"),
            "docker logs --since 10m tinyauth 2>&1 | grep -ciE 'ldap.*(error|failed)' || true": (0, "0\n"),
        }
        return runner(outputs)

    def test_security_runs_the_common_checks_and_its_own(self):
        checks = host.run_checks(self._everything_passes(EXPECTED), EXPECTED)
        assert [c.name for c in checks] == [fn.__name__ for fn in (*host.COMMON_CHECKS, *host.HOST_CHECKS["security"])]
        assert all(c.ok for c in checks)

    def test_another_host_gets_only_the_common_checks(self):
        play = host.Expected("play", "192.168.20.4", "play.internal.example.com", "Asia/Singapore", EXPECTED.probe_image)
        checks = host.run_checks(self._everything_passes(play), play)
        assert [c.name for c in checks] == [fn.__name__ for fn in host.COMMON_CHECKS]


class TestReport:
    def test_all_passing_exits_zero_and_counts(self, capsys):
        assert host.report([host.Check("a", True, "fine")]) == 0
        assert "1/1 checks passed" in capsys.readouterr().out

    def test_a_failure_exits_one_and_names_the_check(self, capsys):
        assert host.report([host.Check("a", True, "fine"), host.Check("b", False, "broken")]) == 1
        out = capsys.readouterr().out
        assert "FAIL  b  broken" in out
        assert "1/2 checks passed; failed: b" in out


class TestSeedImageAndExpected:
    def test_the_digest_pinned_alpine_image_is_read_from_the_seed_task(self, tmp_path):
        tasks = tmp_path / "seed.yaml"
        tasks.write_text("    image: alpine:3.24@sha256:" + "b" * 64 + "\n    command: x\n")
        assert host.seed_image(tasks) == "alpine:3.24@sha256:" + "b" * 64

    def test_a_task_file_without_one_stops(self, tmp_path):
        tasks = tmp_path / "seed.yaml"
        tasks.write_text("image: busybox\n")
        with pytest.raises(SystemExit, match="no alpine image with a digest"):
            host.seed_image(tasks)

    def test_the_real_seed_task_holds_a_pinned_image(self):
        assert host.seed_image().startswith("alpine:")

    def test_expected_takes_the_address_from_dns_and_the_zone_from_the_inventory(self, secrets_dir):
        secrets_dir.seed("main-domain", "example.com")
        expected = host.expected_for("play", resolve=lambda name: {"play.internal.example.com": "192.168.20.4"}[name])
        assert (expected.address, expected.fqdn, expected.timezone) == ("192.168.20.4", "play.internal.example.com", "Asia/Singapore")

    def test_a_name_that_does_not_resolve_stops_with_a_message(self, secrets_dir):
        secrets_dir.seed("main-domain", "example.com")

        def refuse(name):
            raise OSError("no such host")

        with pytest.raises(SystemExit, match="does not resolve from here"):
            host.expected_for("play", resolve=refuse)


class TestSshRunnerAndMain:
    def test_the_runner_returns_the_exit_status_and_text_and_bounds_the_wait(self, ssh_client):
        ssh_client.exec_command.return_value = exec_result(stdout=b"hello\n", exit_status=3)
        assert host.ssh_runner(ssh_client)("echo hello") == (3, "hello\n")
        assert ssh_client.exec_command.call_args.kwargs["timeout"] == host.COMMAND_TIMEOUT_SECONDS

    @pytest.fixture
    def wired(self, monkeypatch, ssh_client):
        monkeypatch.setattr(host, "ssh_target", create_autospec(host.ssh_target, return_value=("secadmin", "security.internal.example.com", "/key")))
        monkeypatch.setattr(host, "expected_for", create_autospec(host.expected_for, return_value=EXPECTED))
        monkeypatch.setattr(host, "connect_ssh", create_autospec(host.connect_ssh, return_value=ssh_client))
        return ssh_client

    def test_a_run_checks_the_named_host_and_closes_the_connection(self, wired, monkeypatch):
        monkeypatch.setattr(host, "run_checks", create_autospec(host.run_checks, return_value=[host.Check("a", True, "fine")]))
        assert host.main(["security"]) == 0
        host.ssh_target.assert_called_once_with("security")
        host.connect_ssh.assert_called_once_with("secadmin", "security.internal.example.com", "/key")
        wired.close.assert_called_once()

    def test_the_connection_is_closed_when_a_check_raises(self, wired, monkeypatch):
        monkeypatch.setattr(host, "run_checks", create_autospec(host.run_checks, side_effect=OSError("channel closed")))
        with pytest.raises(OSError, match="channel closed"):
            host.main(["security"])
        wired.close.assert_called_once()

    @pytest.mark.parametrize("argv", [[], ["a", "b"]])
    def test_a_missing_or_extra_argument_is_a_usage_error(self, argv, capsys):
        assert host.main(argv) == 2
        assert "usage:" in capsys.readouterr().err
