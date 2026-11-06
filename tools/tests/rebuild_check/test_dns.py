"""Unit tests for rebuild_check.dns. Every dig answer is canned; nothing here queries a real server."""

from __future__ import annotations

import subprocess
from unittest.mock import create_autospec

import pytest
import yaml
from rebuild_check import dns

PRIMARY, SECONDARY = "192.168.20.3", "192.168.20.6"
HOST_ZONE, LAN_ZONE = "internal.example.com", "lan.example.com"
PLAN = dns.Plan(
    servers=dns.Servers(PRIMARY, SECONDARY),
    zones=(HOST_ZONE, LAN_ZONE),
    names={f"storage.{HOST_ZONE}": "192.168.20.6", f"s3.store.{LAN_ZONE}": None},
)


def soa(serial: int) -> str:
    return f"ns1.{HOST_ZONE}. hostmaster.{HOST_ZONE}. {serial} 10800 3600 604800 3600\n"


def dig_from(answers: dict[tuple[str, str, str], tuple[int, str]]):
    """A dig that answers only the queries a test names: an unexpected query fails the test."""

    def dig(server: str, name: str, record_type: str) -> tuple[int, str]:
        return answers[(server, name, record_type)]

    return dig


def healthy() -> dict[tuple[str, str, str], tuple[int, str]]:
    answers = {}
    for server in (PRIMARY, SECONDARY):
        answers[(server, HOST_ZONE, "SOA")] = (0, soa(7))
        answers[(server, LAN_ZONE, "SOA")] = (0, soa(9))
        answers[(server, f"storage.{HOST_ZONE}", "A")] = (0, "192.168.20.6\n")
        answers[(server, f"s3.store.{LAN_ZONE}", "A")] = (0, f"storage.{HOST_ZONE}.\n")
    return answers


def by_name(checks):
    return {c.name: c for c in checks}


class TestSerials:
    def test_equal_serials_pass_and_are_printed_for_each_zone(self):
        result = dns.zones_have_one_serial(dig_from(healthy()), PLAN)
        assert result.ok
        assert result.detail.endswith(f": {HOST_ZONE} 7, {LAN_ZONE} 9")

    def test_a_secondary_behind_fails_and_says_which_zone_and_how(self):
        answers = healthy()
        answers[(SECONDARY, HOST_ZONE, "SOA")] = (0, soa(6))
        result = dns.zones_have_one_serial(dig_from(answers), PLAN)
        assert not result.ok
        assert f"{HOST_ZONE}: serial 7 on the primary, 6 on the secondary" in result.detail
        assert LAN_ZONE not in result.detail

    def test_a_server_that_does_not_answer_fails(self):
        answers = healthy()
        answers[(SECONDARY, LAN_ZONE, "SOA")] = (9, "")
        result = dns.zones_have_one_serial(dig_from(answers), PLAN)
        assert (result.ok, f"{SECONDARY} did not answer" in result.detail) == (False, True)

    def test_a_server_with_no_soa_for_the_zone_fails(self):
        answers = healthy()
        answers[(SECONDARY, HOST_ZONE, "SOA")] = (0, "")
        assert f"{SECONDARY} has no SOA for {HOST_ZONE}" in dns.zones_have_one_serial(dig_from(answers), PLAN).detail


class TestNames:
    def test_both_servers_giving_the_inventorys_address_pass(self):
        result = dns.name_resolves_alike(dig_from(healthy()), PLAN, f"storage.{HOST_ZONE}")
        assert (result.ok, result.detail) == (True, "192.168.20.6 as the inventory says")

    def test_the_servers_disagreeing_fails_naming_both_answers(self):
        answers = healthy()
        answers[(PRIMARY, f"storage.{HOST_ZONE}", "A")] = (0, "192.168.20.7\n")
        result = dns.name_resolves_alike(dig_from(answers), PLAN, f"storage.{HOST_ZONE}")
        assert not result.ok
        assert "192.168.20.7" in result.detail
        assert "192.168.20.6" in result.detail

    def test_both_agreeing_on_another_address_than_the_inventorys_fails(self):
        answers = healthy()
        for server in (PRIMARY, SECONDARY):
            answers[(server, f"storage.{HOST_ZONE}", "A")] = (0, "192.168.20.7\n")
        result = dns.name_resolves_alike(dig_from(answers), PLAN, f"storage.{HOST_ZONE}")
        assert (result.ok, "the inventory says 192.168.20.6" in result.detail) == (False, True)

    def test_a_name_with_no_expected_address_needs_only_agreement_and_follows_a_cname(self):
        result = dns.name_resolves_alike(dig_from(healthy()), PLAN, f"s3.store.{LAN_ZONE}")
        assert (result.ok, result.detail) == (True, "192.168.20.6")

    def test_a_cname_answered_with_its_target_in_the_same_reply_is_not_asked_again(self):
        answers = healthy()
        for server in (PRIMARY, SECONDARY):
            answers[(server, f"s3.store.{LAN_ZONE}", "A")] = (0, f"storage.{HOST_ZONE}.\n192.168.20.6\n")
            del answers[(server, f"storage.{HOST_ZONE}", "A")]
        result = dns.name_resolves_alike(dig_from(answers), PLAN, f"s3.store.{LAN_ZONE}")
        assert (result.ok, result.detail) == (True, "192.168.20.6")

    def test_a_chain_of_cnames_is_followed_to_its_address(self):
        answers = healthy()
        for server in (PRIMARY, SECONDARY):
            answers[(server, f"s3.store.{LAN_ZONE}", "A")] = (0, f"alias.{HOST_ZONE}.\n")
            answers[(server, f"alias.{HOST_ZONE}", "A")] = (0, f"storage.{HOST_ZONE}.\n")
        result = dns.name_resolves_alike(dig_from(answers), PLAN, f"s3.store.{LAN_ZONE}")
        assert (result.ok, result.detail) == (True, "192.168.20.6")

    def test_a_cname_whose_target_has_no_address_fails(self):
        answers = healthy()
        answers[(SECONDARY, f"storage.{HOST_ZONE}", "A")] = (0, "")
        result = dns.name_resolves_alike(dig_from(answers), PLAN, f"s3.store.{LAN_ZONE}")
        assert (result.ok, f"{SECONDARY} has no address for s3.store.{LAN_ZONE}" in result.detail) == (False, True)

    def test_a_cname_loop_fails_instead_of_asking_forever(self):
        answers = healthy()
        for server in (PRIMARY, SECONDARY):
            answers[(server, f"s3.store.{LAN_ZONE}", "A")] = (0, f"a.{LAN_ZONE}.\n")
            answers[(server, f"a.{LAN_ZONE}", "A")] = (0, f"s3.store.{LAN_ZONE}.\n")
        result = dns.name_resolves_alike(dig_from(answers), PLAN, f"s3.store.{LAN_ZONE}")
        assert (result.ok, f"{PRIMARY} has no address for s3.store.{LAN_ZONE}" in result.detail) == (False, True)

    def test_a_server_that_answers_nothing_for_the_name_fails(self):
        answers = healthy()
        answers[(SECONDARY, f"storage.{HOST_ZONE}", "A")] = (0, "")
        result = dns.name_resolves_alike(dig_from(answers), PLAN, f"storage.{HOST_ZONE}")
        assert f"{SECONDARY} has no address for storage.{HOST_ZONE}" in result.detail


class TestRunChecks:
    def test_a_healthy_pair_passes_every_check(self):
        checks = dns.run_checks(dig_from(healthy()), PLAN)
        assert [c.ok for c in checks] == [True, True, True]
        assert [c.name for c in checks] == ["zones_have_one_serial", f"resolves_alike: storage.{HOST_ZONE}", f"resolves_alike: s3.store.{LAN_ZONE}"]

    def test_one_failure_does_not_hide_the_others(self):
        answers = healthy()
        answers[(SECONDARY, HOST_ZONE, "SOA")] = (0, soa(6))
        checks = by_name(dns.run_checks(dig_from(answers), PLAN))
        assert [checks["zones_have_one_serial"].ok, checks[f"resolves_alike: storage.{HOST_ZONE}"].ok] == [False, True]


class TestPlan:
    @pytest.fixture
    def files(self, tmp_path, monkeypatch):
        group_vars = tmp_path / "all.yaml"
        group_vars.write_text(yaml.safe_dump({"dns_primary_address": PRIMARY, "dns_secondary_address": SECONDARY}))
        inventory = tmp_path / "inventory.yaml"
        inventory.write_text(
            yaml.safe_dump(
                {"all": {"children": {"managed_hosts": {"hosts": {"services": {}, "storage": None}}, "network_infra": {"hosts": {"tailscale": {}}}}}}
            )
        )
        generated = tmp_path / "tofu-hosts.yaml"
        generated.write_text(yaml.safe_dump({"all": {"hosts": {"storage": {"ansible_host": "192.168.20.6", "ansible_user": "storeadmin"}}}}))
        monkeypatch.setattr(dns, "GROUP_VARS", group_vars)
        monkeypatch.setattr(dns, "INVENTORY_PATH", inventory)
        monkeypatch.setattr(dns, "GENERATED_INVENTORY_PATH", generated)
        monkeypatch.setattr(dns, "main_domain", lambda: "example.com")

    @pytest.mark.usefixtures("files")
    def test_every_inventory_host_is_checked_and_only_tofus_have_an_expected_address(self):
        plan = dns.plan_for([])
        assert plan.names == {
            f"services.{HOST_ZONE}": None,
            f"storage.{HOST_ZONE}": "192.168.20.6",
            f"tailscale.{HOST_ZONE}": None,
            f"s3.store.{LAN_ZONE}": None,
        }
        assert (plan.servers, plan.zones) == (dns.Servers(PRIMARY, SECONDARY), (HOST_ZONE, LAN_ZONE))

    @pytest.mark.usefixtures("files")
    def test_naming_hosts_limits_the_names(self):
        assert list(dns.plan_for(["storage"]).names) == [f"storage.{HOST_ZONE}", f"s3.store.{LAN_ZONE}"]

    @pytest.mark.usefixtures("files")
    def test_a_host_the_inventory_lacks_is_an_error(self):
        with pytest.raises(SystemExit, match=r"unknown host.*nas"):
            dns.plan_for(["nas"])


def test_a_flag_prints_the_usage_and_queries_nothing(capsys):
    assert dns.main(["--all"]) == 2
    assert "usage:" in capsys.readouterr().err


def test_dig_asks_the_named_server_for_the_short_answer(monkeypatch):
    run = create_autospec(subprocess.run, return_value=subprocess.CompletedProcess([], 0, stdout="192.168.20.6\n"))
    monkeypatch.setattr(dns.subprocess, "run", run)
    assert dns.dig_runner(SECONDARY, "storage.internal.example.com", "A") == (0, "192.168.20.6\n")
    assert run.call_args.args[0] == ["dig", "+short", "+time=3", "+tries=1", f"@{SECONDARY}", "storage.internal.example.com", "A"]
