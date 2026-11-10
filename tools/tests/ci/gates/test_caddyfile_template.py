"""The Caddyfile template: which routes get forward auth and which are limited to read methods."""

from __future__ import annotations

from pathlib import Path

import jinja2
import pytest

TEMPLATE = Path(__file__).resolve().parents[4] / "ansible" / "roles" / "caddy" / "templates" / "Caddyfile.j2"
FORWARD_AUTH = "import tinyauth_forwarder *"
READ_ONLY = "Method Not Allowed"


def render(route: dict[str, object]) -> str:
    app = {"name": "web", "routes": {"default": {"host": "web", "upstream": "web:80", **route}}}
    env = jinja2.Environment(autoescape=False, trim_blocks=True, lstrip_blocks=True)  # noqa: S701 - a Caddyfile, not HTML
    variables = {"caddy_local_certs": True, "tinyauth_host": "auth", "lan_domain": "lab.test", "caddy_domain": "lab.test", "resolved_apps": [app]}
    return env.from_string(TEMPLATE.read_text()).render(**variables)


def route_block(text: str) -> str:
    start = text.index("handle @web {")
    return text[start : text.index("\n    }\n", start)]


def test_a_route_with_no_auth_key_is_behind_forward_auth() -> None:
    assert FORWARD_AUTH in route_block(render({}))


def test_a_route_with_auth_true_is_behind_forward_auth() -> None:
    assert FORWARD_AUTH in route_block(render({"auth": True}))


def test_only_an_explicit_false_opts_a_route_out_of_forward_auth() -> None:
    assert FORWARD_AUTH not in route_block(render({"auth": False}))


@pytest.mark.parametrize("value", ["", None, 0, "false", "no"], ids=["empty", "null", "zero", "quoted-false", "quoted-no"])
def test_any_other_auth_value_keeps_forward_auth(value: object) -> None:
    assert FORWARD_AUTH in route_block(render({"auth": value}))


def test_a_route_without_read_only_accepts_every_method() -> None:
    assert READ_ONLY not in render({})


def test_a_read_only_false_accepts_every_method() -> None:
    assert READ_ONLY not in render({"read_only": False})


@pytest.mark.parametrize("value", [True, "", "yes", 1], ids=["true", "empty", "quoted-yes", "one"])
def test_any_read_only_value_other_than_false_limits_the_route_to_read_methods(value: object) -> None:
    assert READ_ONLY in render({"read_only": value})
