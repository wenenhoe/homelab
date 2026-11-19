"""Tests for the management reach check, with the connection stood in by a table of what is reachable."""

from __future__ import annotations

import management_reach
import pytest

GATEWAY = "192.168.77.1"
ALLOWED = "192.168.77.10"
OTHER = "192.168.77.11"


def reaching(*reached: tuple[str, int]):
    def connect(gateway: str, port: int, source: str) -> bool:
        assert gateway == GATEWAY
        return (source, port) in reached

    return connect


def test_passes_when_only_the_admitted_address_reaches_the_gui_port(capsys):
    assert management_reach.run(GATEWAY, ALLOWED, OTHER, reaching((ALLOWED, 443))) == 0

    assert capsys.readouterr().out.count("PASS") == 4


@pytest.mark.parametrize(
    "reached",
    [
        pytest.param([], id="the admitted address cannot reach the gateway, so the probe proves nothing"),
        pytest.param([(ALLOWED, 443), (OTHER, 443)], id="another address reaches the GUI port"),
        pytest.param([(ALLOWED, 443), (OTHER, 22)], id="another address reaches the SSH port"),
        pytest.param([(ALLOWED, 443), (ALLOWED, 22)], id="the SSH port is open"),
    ],
)
def test_fails_when_the_reach_differs_from_the_seeds(reached, capsys):
    assert management_reach.run(GATEWAY, ALLOWED, OTHER, reaching(*reached)) == 1

    assert "FAIL" in capsys.readouterr().out


def test_three_different_addresses_are_required(capsys):
    assert management_reach.main([GATEWAY, ALLOWED, ALLOWED]) == 2

    assert "usage" in capsys.readouterr().err
