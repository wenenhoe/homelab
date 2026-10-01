"""Tests for ci.fixtures: the two fixture writers the deploy-ordering job runs.

Most cases build a scratch repo holding a small catalog; TestRealCatalog
runs the same code over the real secret_catalog.yaml (writing into a
temporary tree, never into ansible/files/secrets), and TestRealWorkflow holds
the deploy-ordering job's steps to what the code and the gate module expect.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest
import yaml
from ci.fixtures import file_cache_catalog as fcr
from ci.fixtures import preseed_manual_secrets as pre
from ci.gates import deploy_ordering
from utils import secret_catalog as sr

REPO_ROOT = sr.REPO_ROOT

CATALOG = {
    "cf-token": {"source": "manual", "description": "d", "sensitive": True, "store": "openbao", "scope": "hosts/all"},
    "beszel-key": {"source": "manual", "allow_blank": True, "store": "openbao", "scope": "hosts/play"},
    "main-domain": {"source": "manual", "store": "controller_file"},
    "role-id": {"source": "manual", "allow_blank": True, "store": "controller_file"},
    "session-key": {"source": "hex", "length": 32, "store": "openbao", "scope": "hosts/all"},
    "request-id": {"source": "uuid4", "store": "openbao", "scope": "hosts/all"},
}


def write_catalog(root: Path, catalog: object = None, text: str | None = None) -> Path:
    path = root / sr.CATALOG_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text is not None else yaml.safe_dump({"secret_catalog": CATALOG if catalog is None else catalog}))
    return path


class TestManualValues:
    def test_only_manual_file_cache_entries_get_a_value(self):
        assert set(pre.manual_values(CATALOG)) == {"main-domain", "role-id"}

    def test_allow_blank_entries_get_an_empty_string_and_the_rest_a_traceable_dummy(self):
        values = pre.manual_values(CATALOG)
        assert values["role-id"] == ""
        assert values["main-domain"] == "ci-dummy-main-domain"

    def test_allow_blank_false_or_missing_is_not_blank(self):
        values = pre.manual_values(
            {"a": {"source": "manual", "allow_blank": False, "store": "controller_file"}, "b": {"source": "manual", "store": "controller_file"}}
        )
        assert values == {"a": "ci-dummy-a", "b": "ci-dummy-b"}

    @pytest.mark.parametrize(
        "key",
        [
            pytest.param("../escape", id="parent-traversal"),
            pytest.param("a/b", id="contains-a-slash"),
            pytest.param("/abs", id="absolute-path"),
            pytest.param("..", id="parent-directory"),
            pytest.param(".", id="current-directory"),
            pytest.param("", id="empty"),
        ],
    )
    def test_a_key_that_is_not_a_plain_file_name_is_refused(self, key):
        with pytest.raises(sr.CatalogError, match="can't be used as a file name"):
            pre.manual_values({key: {"source": "manual", "store": "controller_file"}})

    def test_an_unsafe_key_on_a_non_manual_entry_is_not_a_file_and_is_ignored(self):
        assert pre.manual_values({"../x": {"source": "hex", "store": "openbao", "scope": "hosts/play"}}) == {}

    def test_an_openbao_stored_manual_entry_is_not_a_file_and_is_ignored(self):
        assert pre.manual_values({"../x": {"source": "manual", "store": "openbao", "scope": "hosts/all/x"}}) == {}


class TestPreseed:
    def test_writes_one_file_per_manual_file_cache_secret_with_exact_contents(self, root):
        write_catalog(root)
        written, secrets_dir = pre.preseed(root)
        assert written == 2
        assert secrets_dir == root / pre.SECRETS_RELATIVE
        assert sorted(p.name for p in secrets_dir.iterdir()) == ["main-domain", "role-id"]
        assert (secrets_dir / "role-id").read_bytes() == b""
        assert (secrets_dir / "main-domain").read_bytes() == b"ci-dummy-main-domain"

    def test_overwrites_an_existing_file_and_keeps_unrelated_ones(self, root):
        write_catalog(root)
        secrets_dir = root / pre.SECRETS_RELATIVE
        secrets_dir.mkdir(parents=True)
        (secrets_dir / "main-domain").write_text("stale")
        (secrets_dir / "unrelated").write_text("keep")
        pre.preseed(root)
        assert (secrets_dir / "main-domain").read_text() == "ci-dummy-main-domain"
        assert (secrets_dir / "unrelated").read_text() == "keep"

    def test_a_catalog_with_no_manual_entries_writes_nothing(self, root):
        write_catalog(root, {"a": {"source": "hex", "store": "openbao", "scope": "hosts/play"}})
        written, secrets_dir = pre.preseed(root)
        assert written == 0
        assert list(secrets_dir.iterdir()) == []

    def test_an_unsafe_key_writes_nothing_at_all(self, root):
        write_catalog(root, {"ok": {"source": "manual", "store": "controller_file"}, "../bad": {"source": "manual", "store": "controller_file"}})
        with pytest.raises(sr.CatalogError):
            pre.preseed(root)
        assert not (root / pre.SECRETS_RELATIVE / "ok").exists()

    def test_main_prints_the_summary_and_reports_a_bad_catalog_as_a_failure(self, root, monkeypatch):
        write_catalog(root)
        out = io.StringIO()
        monkeypatch.setattr(pre, "REPO_ROOT", root)
        with redirect_stdout(out):
            assert pre.main() == 0
        assert "Pre-seeded 2 manual secrets" in out.getvalue()
        write_catalog(root, text="[]")
        err = io.StringIO()
        with redirect_stderr(err):
            assert pre.main() == 1
        assert "::error::" in err.getvalue()


class TestFileCacheCatalog:
    def test_keeps_only_the_controller_file_entries_and_every_field_of_them(self):
        override = fcr.file_cache_catalog(CATALOG)
        assert override == {"main-domain": CATALOG["main-domain"], "role-id": CATALOG["role-id"]}

    def test_does_not_mutate_its_input(self):
        original = json.loads(json.dumps(CATALOG))
        fcr.file_cache_catalog(CATALOG)
        assert original == CATALOG

    @pytest.mark.parametrize(
        "catalog",
        [
            pytest.param({"role-id": CATALOG["role-id"]}, id="main-domain-missing"),
            pytest.param({"main-domain": {"source": "manual", "store": "openbao", "scope": "hosts/all/x"}}, id="main-domain-stored-in-openbao"),
        ],
    )
    def test_a_catalog_whose_main_domain_is_not_a_file_cache_entry_is_an_error(self, catalog):
        with pytest.raises(sr.CatalogError, match="main-domain"):
            fcr.file_cache_catalog(catalog)

    def test_main_writes_json_under_a_secret_catalog_key_that_ansible_can_load(self, root, monkeypatch):
        catalog_path = write_catalog(root)
        target = root / "out.json"
        out = io.StringIO()
        monkeypatch.setattr(fcr, "CATALOG_PATH", catalog_path)
        with redirect_stdout(out):
            assert fcr.main([str(target)]) == 0
        assert json.loads(target.read_text()) == {"secret_catalog": fcr.file_cache_catalog(CATALOG)}
        assert "Wrote 2 file-cache entries" in out.getvalue()

    def test_main_reports_a_bad_catalog_without_writing(self, root, monkeypatch):
        target = root / "out.json"
        err = io.StringIO()
        monkeypatch.setattr(fcr, "CATALOG_PATH", root / "missing.yaml")
        with redirect_stderr(err):
            assert fcr.main([str(target)]) == 1
        assert "::error::" in err.getvalue()
        assert not target.exists()

    def test_main_reports_a_catalog_without_main_domain_without_writing(self, root, monkeypatch):
        catalog_path = write_catalog(root, {"role-id": CATALOG["role-id"]})
        target = root / "out.json"
        monkeypatch.setattr(fcr, "CATALOG_PATH", catalog_path)
        with redirect_stderr(io.StringIO()):
            assert fcr.main([str(target)]) == 1
        assert not target.exists()

    def test_main_requires_an_output_path(self):
        with redirect_stderr(io.StringIO()), pytest.raises(SystemExit) as raised:
            fcr.main([])
        assert raised.value.code == 2


@pytest.fixture(scope="module")
def catalog():
    return sr.load_catalog()


class TestRealCatalog:
    def test_every_manual_file_cache_entry_is_seeded_and_no_other(self, catalog):
        manual = {key for key, spec in catalog.items() if spec.get("source") == "manual" and spec.get("store") == "controller_file"}
        assert manual
        assert set(pre.manual_values(catalog)) == manual

    def test_the_real_catalog_seeds_into_a_temporary_tree(self, catalog, root):
        target = root / sr.CATALOG_RELATIVE
        target.parent.mkdir(parents=True)
        target.write_text((REPO_ROOT / sr.CATALOG_RELATIVE).read_text())
        written, secrets_dir = pre.preseed(root)
        assert written == len(list(secrets_dir.iterdir()))
        blank = {key for key, spec in sr.file_cache_entries(catalog).items() if spec.get("source") == "manual" and spec.get("allow_blank")}
        assert blank
        for key in blank:
            assert (secrets_dir / key).read_text() == "", key

    def test_the_real_override_is_exactly_the_controller_file_entries_and_includes_main_domain(self, catalog, subtests):
        override = fcr.file_cache_catalog(catalog)
        assert set(override) == {key for key, spec in catalog.items() if spec["store"] == "controller_file"}
        assert "main-domain" in override
        for key, spec in override.items():
            with subtests.test(key=key):
                assert spec == catalog[key]

    def test_the_real_catalog_has_entries_stored_in_openbao_that_the_override_leaves_out(self, catalog):
        assert any(spec["store"] == "openbao" for spec in catalog.values())
        assert not any(spec["store"] == "openbao" for spec in fcr.file_cache_catalog(catalog).values())


@pytest.fixture(scope="module")
def steps():
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/pr-checks.yml").read_text())
    return workflow["jobs"]["deploy-ordering-check"]["steps"]


def step_running(steps, module: str) -> dict[str, str]:
    return next(step for step in steps if module in step.get("run", ""))


class TestRealWorkflow:
    @pytest.mark.parametrize("module", ["ci.fixtures.preseed_manual_secrets", "ci.fixtures.file_cache_catalog"])
    def test_the_steps_run_the_modules_from_tools_under_uv(self, steps, module):
        step = step_running(steps, module)
        assert step["run"].startswith(f"uv run python -m {module}")
        assert step["working-directory"] == "tools"

    def test_the_catalog_override_path_matches_what_the_gate_module_passes_to_ansible(self, steps):
        argument = step_running(steps, "ci.fixtures.file_cache_catalog")["run"].split()[-1]
        assert f"@{argument}" == deploy_ordering.CATALOG_OVERRIDE

    def test_both_fixtures_run_before_the_playbooks(self, steps):
        names = [step["run"] for step in steps if "run" in step]
        order = {
            module: next(i for i, run in enumerate(names) if module in run)
            for module in ("preseed_manual_secrets", "file_cache_catalog", "ci.gates.deploy_ordering deploy")
        }
        assert order["preseed_manual_secrets"] < order["ci.gates.deploy_ordering deploy"]
        assert order["file_cache_catalog"] < order["ci.gates.deploy_ordering deploy"]

    def test_the_job_reruns_when_a_fixture_changes(self):
        filters = yaml.safe_load((REPO_ROOT / ".github/detect-changes-filters.yml").read_text())
        assert "tools/ci/fixtures/**" in filters["deploy_ordering"]

    def test_the_job_reruns_when_the_loader_the_fixtures_read_the_catalog_with_changes(self):
        filters = yaml.safe_load((REPO_ROOT / ".github/detect-changes-filters.yml").read_text())
        assert "tools/utils/secret_catalog.py" in filters["deploy_ordering"]
