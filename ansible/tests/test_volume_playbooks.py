"""The ad hoc volume playbooks refuse to touch more than one host.

An app such as caddy is declared on every managed host, so a run without
--limit would reset or empty the same volume on all of them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

PLAYBOOKS = Path(__file__).resolve().parents[1] / "playbooks"


@pytest.mark.parametrize("playbook", [pytest.param("volume-reset.yaml", id="volume-reset"), pytest.param("volume-file-rm.yaml", id="volume-file-rm")])
def test_the_play_that_changes_a_volume_first_requires_exactly_one_host(playbook):
    plays = [play for play in yaml.safe_load((PLAYBOOKS / playbook).read_text()) if play.get("hosts") == "app_hosts"]

    assert len(plays) == 1
    first = plays[0]["tasks"][0]
    assert first["ansible.builtin.assert"]["that"] == "ansible_play_hosts_all | length == 1"
