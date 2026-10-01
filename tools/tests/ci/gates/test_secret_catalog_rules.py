"""Tests for ci.gates.secret_catalog_rules: one case per rule, then the real catalog.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout

import pytest
from ci.gates import secret_catalog_rules as rules
from utils.secret_catalog import load_catalog

GOOD = {
    "session-key": {"source": "hex", "length": 32, "store": "openbao", "scope": "hosts/services"},
    "request-id": {"source": "uuid4", "store": "openbao", "scope": "hosts/all/shlink"},
    "api-token": {"source": "manual", "description": "d", "sensitive": True, "allow_blank": False, "store": "openbao", "scope": "cloud_credentials/leaf"},
    "main-domain": {"source": "manual", "description": "The main domain", "store": "controller_file"},
}
OPENBAO = {"store": "openbao", "scope": "hosts/play"}
FILE_CACHE = {"store": "controller_file"}


def broken(name: str, spec: dict[str, object]) -> list[str]:
    """The rule ids `spec` breaks when it is the only entry."""
    return [violation.rule for violation in rules.validate({name: spec})]


def cases(*values: object) -> list[object]:
    """One case per value, with its repr as the id."""
    return [pytest.param(value, id=repr(value)) for value in values]


class TestEachRule:
    def test_a_catalog_that_follows_every_rule_has_no_violations(self):
        assert rules.validate(GOOD) == []
        assert rules.validate({}) == []

    @pytest.mark.parametrize("name", cases("Session_Key", "session--key", "-session", "session-", "session key", "a/b", ""))
    def test_name_must_be_kebab_case(self, name):
        assert broken(name, {"source": "uuid4", **OPENBAO}) == ["name"]

    def test_an_unknown_key_is_refused_so_a_typo_cannot_change_an_entry(self):
        assert broken("a", {"source": "manual", "description": "d", "store": "openbao", "scope": "hosts/play", "scop": "x"}) == ["unknown-key"]

    def test_the_old_field_names_are_unknown_keys(self):
        assert "unknown-key" in broken("a", {"format": "uuid4", "source": "uuid4", **OPENBAO})
        assert "unknown-key" in broken("a", {"source": "uuid4", "vault_scope": "hosts/play", **OPENBAO})

    @pytest.mark.parametrize(
        "spec",
        [
            pytest.param({**OPENBAO}, id="source-missing"),
            pytest.param({"source": "base64", **OPENBAO}, id="source-unknown"),
            pytest.param({"source": None, **OPENBAO}, id="source-null"),
        ],
    )
    def test_source_must_be_hex_uuid4_or_manual(self, spec):
        assert "source" in broken("a", spec)

    @pytest.mark.parametrize(
        "extra",
        [
            pytest.param({}, id="store-missing"),
            pytest.param({"store": "vault"}, id="store-unknown"),
            pytest.param({"store": None}, id="store-null"),
            pytest.param({"store": ""}, id="store-empty"),
            pytest.param({"store": "OpenBao"}, id="store-wrong-case"),
        ],
    )
    def test_store_is_required_and_must_be_openbao_or_controller_file(self, extra):
        assert "store" in broken("a", {"source": "manual", "description": "d", **extra})

    @pytest.mark.parametrize(
        "length",
        [
            pytest.param({}, id="length-missing"),
            pytest.param({"length": 0}, id="zero"),
            pytest.param({"length": -4}, id="negative"),
            pytest.param({"length": "32"}, id="string"),
            pytest.param({"length": True}, id="boolean"),
            pytest.param({"length": 8.5}, id="float"),
        ],
    )
    def test_hex_requires_a_positive_integer_length(self, length):
        assert broken("a", {"source": "hex", **OPENBAO, **length}) == ["length-required"]

    def test_other_sources_forbid_length(self):
        assert broken("a", {"source": "uuid4", "length": 32, **OPENBAO}) == ["length-forbidden"]
        assert broken("a", {"source": "manual", "length": 32, "description": "d", **FILE_CACHE}) == ["length-forbidden"]

    def test_store_openbao_requires_a_scope(self):
        assert broken("a", {"source": "manual", "description": "d", "store": "openbao"}) == ["scope-required"]
        assert broken("a", {"source": "uuid4", "store": "openbao"}) == ["scope-required"]

    def test_store_controller_file_forbids_a_scope(self):
        assert broken("a", {"source": "manual", "description": "d", "store": "controller_file", "scope": "hosts/play"}) == ["scope-forbidden"]

    def test_generated_sources_require_store_openbao(self):
        assert broken("a", {"source": "hex", "length": 32, **FILE_CACHE}) == ["generated-store"]
        assert broken("a", {"source": "uuid4", **FILE_CACHE}) == ["generated-store"]

    def test_a_manual_secret_may_be_stored_in_either_place(self):
        assert broken("a", {"source": "manual", "description": "d", **FILE_CACHE}) == []
        assert broken("a", {"source": "manual", "description": "d", **OPENBAO}) == []

    @pytest.mark.parametrize(
        "scope",
        cases(
            "",
            "hosts",
            "hosts/other",
            "hosts/all",
            "hosts/all/Caddy",
            "hosts/security/",
            "/hosts/security",
            "cloud_credentials/rotation",
            "secret/hosts/play",
            None,
            7,
        ),
    )
    def test_scope_must_be_one_of_the_headers_shapes(self, scope):
        assert broken("a", {"source": "uuid4", "store": "openbao", "scope": scope}) == ["scope-shape"]

    @pytest.mark.parametrize(
        "scope",
        cases("hosts/security", "hosts/services", "hosts/storage", "hosts/play", "hosts/all/caddy-acme", "hosts/all/step-ca", "cloud_credentials/leaf"),
    )
    def test_every_shape_the_header_names_is_accepted(self, scope):
        assert broken("a", {"source": "uuid4", "store": "openbao", "scope": scope}) == []

    @pytest.mark.parametrize(
        "extra",
        [
            pytest.param({}, id="description-missing"),
            pytest.param({"description": ""}, id="empty"),
            pytest.param({"description": "   "}, id="blank"),
            pytest.param({"description": None}, id="null"),
            pytest.param({"description": 3}, id="number"),
        ],
    )
    def test_manual_requires_a_non_empty_description(self, extra):
        assert broken("a", {"source": "manual", **FILE_CACHE, **extra}) == ["description-required"]

    @pytest.mark.parametrize(
        ("flag", "spec"),
        [
            pytest.param(flag, spec, id=f"{flag}-{spec['source']}")
            for flag in ("allow_blank", "sensitive")
            for spec in ({"source": "uuid4", **OPENBAO}, {"source": "hex", "length": 8, **OPENBAO})
        ],
    )
    def test_allow_blank_and_sensitive_are_valid_only_on_manual(self, flag, spec):
        assert broken("a", {**spec, flag: True}) == ["flag-manual-only"]

    @pytest.mark.parametrize(
        ("flag", "value"),
        [pytest.param(flag, value, id=f"{flag}={value!r}") for flag in ("allow_blank", "sensitive") for value in ("true", "yes", 1, 0, None)],
    )
    def test_allow_blank_and_sensitive_must_be_booleans(self, flag, value):
        assert broken("a", {"source": "manual", "description": "d", **FILE_CACHE, flag: value}) == ["flag-boolean"]

    def test_every_violation_in_an_entry_is_reported_not_just_the_first(self):
        found = broken("Bad_Name", {"source": "hex", "scop": "x", "sensitive": True, "store": "controller_file"})
        assert sorted(found) == ["flag-manual-only", "generated-store", "length-required", "name", "unknown-key"]

    def test_violations_name_the_entry_and_come_in_entry_order(self):
        found = rules.validate({"ok": GOOD["main-domain"], "one": {"source": "uuid4", "store": "openbao"}, "two": {"source": "hex", "length": 8, **FILE_CACHE}})
        assert [(v.name, v.rule) for v in found] == [("one", "scope-required"), ("two", "generated-store")]


@pytest.fixture
def run_main(tmp_path_factory, monkeypatch):
    path = tmp_path_factory.mktemp("catalog") / "catalog.yaml"

    def run(text: str | None) -> tuple[int, str, str]:
        if text is not None:
            path.write_text(text)
        out, err = io.StringIO(), io.StringIO()
        monkeypatch.setattr(rules, "CATALOG_PATH", path)
        with redirect_stdout(out), redirect_stderr(err):
            code = rules.main()
        return code, out.getvalue(), err.getvalue()

    return run


class TestMain:
    def test_passes_a_clean_catalog(self, run_main):
        code, out, err = run_main("secret_catalog:\n  a: { source: uuid4, store: openbao, scope: hosts/play }\n")
        assert (code, err) == (0, "")
        assert "follows the header's rules" in out

    def test_fails_and_names_each_violation_and_its_rule(self, run_main):
        code, _, err = run_main("secret_catalog:\n  a: { source: hex, length: 8, store: openbao }\n  b: { source: manual, store: controller_file }\n")
        assert code == 1
        assert "::error::a:" in err
        assert "[scope-required]" in err
        assert "::error::b:" in err
        assert "[description-required]" in err
        assert "2 rule violation(s)" in err

    def test_fails_on_an_unreadable_catalog(self, run_main):
        code, _, err = run_main(None)
        assert code == 1
        assert "::error::can't read" in err

    def test_fails_on_a_repeated_name(self, run_main):
        code, _, err = run_main(
            "secret_catalog:\n"
            "  a: { source: manual, description: d, store: controller_file }\n"
            "  a: { source: manual, description: d, store: controller_file }\n"
        )
        assert code == 1
        assert "duplicate key" in err


class TestRealCatalog:
    def test_the_real_catalog_follows_every_rule(self):
        assert rules.validate(load_catalog()) == []

    def test_main_passes_on_the_real_catalog(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            assert rules.main() == 0

    def test_every_real_entry_states_its_store(self):
        assert all(spec.get("store") in ("openbao", "controller_file") for spec in load_catalog().values())
