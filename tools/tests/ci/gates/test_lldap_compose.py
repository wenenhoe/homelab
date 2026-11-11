"""The lldap compose template: LDAPS stays on the proxy network, under the certificate's name."""

from __future__ import annotations

from pathlib import Path

import jinja2
import yaml

TEMPLATE = Path(__file__).resolve().parents[4] / "docker" / "lldap" / "compose.yaml.j2"


def service() -> dict[str, object]:
    env = jinja2.Environment(autoescape=False, undefined=jinja2.StrictUndefined)  # noqa: S701 - YAML, not HTML
    text = env.from_string(TEMPLATE.read_text()).render(server_timezone="UTC", lldap_host="lldap", caddy_domain="sec.lab.test")
    return yaml.safe_load(text)["services"]["lldap"]


def test_no_port_is_published_on_the_host() -> None:
    assert "ports" not in service()


def test_the_certificate_name_resolves_to_the_container_on_the_proxy_network() -> None:
    assert service()["networks"]["caddy-proxy"]["aliases"] == ["lldap.sec.lab.test"]


def test_ldaps_and_the_web_ui_are_exposed_to_the_network_only() -> None:
    assert service()["expose"] == ["6360", "17170"]
