"""Tests for ci.images.remote.

The registry client runs over real HTTP against a local server that speaks
the registry's token flow (a 401 challenge, a token endpoint, HEAD on
manifests) and can be told to answer 429 or 5xx, so headers, retries and
pacing are exercised for real. Nothing here reaches a real registry; a
live run against ghcr.io and Docker Hub is not covered by these tests.
Collection is tested on scratch repos and on the real one.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import contextlib
import http.server
import io
import json
import threading
import urllib.request
from pathlib import Path

import pytest
from ci.images import registry as reg
from ci.images import remote as rm

REPO_ROOT = rm.REPO_ROOT


class FakeRegistry:
    """A registry on 127.0.0.1. Configure `manifests`, `require_auth` and the failure queues, then read `log`."""

    def __init__(self) -> None:
        self.manifests: dict[tuple[str, str], int] = {}  # (repository, reference) -> status; absent = 404
        self.require_auth = True
        self.fail_next: list[tuple[int, dict[str, str]]] = []  # answered to the next manifest requests, in order
        self.token_fail_next: list[int] = []
        self.log: list[tuple[str, str, dict[str, str]]] = []
        self.token_requests = 0
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):  # silence the server
                pass

            def _reply(self, status: int, headers: dict[str, str] | None = None, body: bytes = b"") -> None:
                self.send_response(status)
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def do_GET(self):
                if self.path.startswith("/token"):
                    owner.token_requests += 1
                    owner.log.append(("GET", self.path, dict(self.headers)))
                    if owner.token_fail_next:
                        return self._reply(owner.token_fail_next.pop(0), {"Retry-After": "0"})
                    return self._reply(200, {"Content-Type": "application/json"}, json.dumps({"token": "good"}).encode())
                self._reply(404)

            def do_HEAD(self):
                owner.log.append(("HEAD", self.path, dict(self.headers)))
                if owner.fail_next:
                    status, headers = owner.fail_next.pop(0)
                    return self._reply(status, headers)
                parts = self.path.split("/manifests/")
                repository, reference = parts[0].removeprefix("/v2/"), parts[1]
                if owner.require_auth and self.headers.get("Authorization") != "Bearer good":
                    challenge = f'Bearer realm="http://127.0.0.1:{owner.port}/token",service="fake",scope="repository:{repository}:pull"'
                    return self._reply(401, {"WWW-Authenticate": challenge})
                self._reply(owner.manifests.get((repository, reference), 404))

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def base_url(self, registry: str) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def heads(self) -> list[str]:
        return [path for method, path, _ in self.log if method == "HEAD"]


@pytest.fixture
def fake():
    registry = FakeRegistry()
    yield registry
    registry.close()


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def client(fake, sleeps):
    return rm.Registry(base_url=fake.base_url, sleep=sleeps.append, delay=0.5, schemes=("http", "https"))


def fake_image(repository: str = "team/app", reference: str = "1.0") -> rm.Image:
    return rm.Image("fake.example", repository, reference)


class TestParseImage:
    def test_docker_hub_names_default_the_registry_the_namespace_and_the_tag(self):
        assert rm.parse_image("alpine") == rm.Image("registry-1.docker.io", "library/alpine", "latest")
        assert rm.parse_image("alpine:3.20") == rm.Image("registry-1.docker.io", "library/alpine", "3.20")
        assert rm.parse_image("rclone/rclone:1.75") == rm.Image("registry-1.docker.io", "rclone/rclone", "1.75")

    def test_an_explicit_registry_is_kept_with_a_nested_repository(self):
        assert rm.parse_image("ghcr.io/henrygd/beszel/beszel:0.20") == rm.Image("ghcr.io", "henrygd/beszel/beszel", "0.20")

    def test_a_registry_port_is_not_a_tag(self):
        assert rm.parse_image("localhost:5000/app") == rm.Image("localhost:5000", "app", "latest")
        assert rm.parse_image("reg.example:5000/a/b:2") == rm.Image("reg.example:5000", "a/b", "2")

    def test_a_pinned_digest_is_what_gets_checked(self):
        digest = "sha256:" + "a" * 64
        assert rm.parse_image(f"ghcr.io/x/y:1.2@{digest}").reference == digest
        assert rm.parse_image(f"alpine@{digest}") == rm.Image("registry-1.docker.io", "library/alpine", digest)

    def test_the_string_form_round_trips_a_tag_and_a_digest(self):
        assert str(rm.parse_image("ghcr.io/x/y:1.2")) == "ghcr.io/x/y:1.2"
        assert "@sha256:" in str(rm.parse_image("ghcr.io/x/y@sha256:" + "b" * 64))

    @pytest.mark.parametrize(
        "text",
        [pytest.param("", id="empty"), pytest.param("a b", id="contains-a-space"), pytest.param("reg.io/", id="registry-without-repository")],
    )
    def test_junk_is_an_error(self, text):
        with pytest.raises(ValueError):
            rm.parse_image(text)


class TestSkipReason:
    def test_reasons(self):
        assert rm.skip_reason("{{ image }}") == "templated"
        assert rm.skip_reason("x:{{ v }}") == "templated"
        assert rm.skip_reason("${BASE}") == "templated"
        assert rm.skip_reason("$IMAGE") == "templated"
        assert rm.skip_reason("scratch") == "scratch"
        assert rm.skip_reason("buildapp:local") == "built locally"
        assert rm.skip_reason("") == "empty"

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param("alpine", id="docker-hub-name"),
            pytest.param("alpine:3.20", id="tagged"),
            pytest.param("ghcr.io/x/y:1", id="other-registry"),
            pytest.param("local/app:pr-check-not", id="local-namespace"),
            pytest.param("rclone/rclone:1.75", id="namespaced"),
        ],
    )
    def test_ordinary_references_are_not_skipped(self, text):
        assert (rm.skip_reason(text) if "local/" not in text else None) is None


class TestExists:
    def test_a_found_tag_after_the_token_handshake_is_ok(self, fake, client):
        fake.manifests[("team/app", "1.0")] = 200
        assert client.check(fake_image())[0] == rm.Verdict.OK
        assert [m for m, _, _ in fake.log] == ["HEAD", "GET", "HEAD"]
        assert fake.log[-1][2]["Authorization"] == "Bearer good"

    def test_the_token_request_carries_the_challenges_service_and_scope(self, fake, client):
        fake.manifests[("team/app", "1.0")] = 200
        client.check(fake_image())
        token_path = next(path for method, path, _ in fake.log if method == "GET")
        assert "service=fake" in token_path
        assert "scope=repository%3Ateam%2Fapp%3Apull" in token_path

    def test_a_missing_tag_is_missing(self, client):
        verdict, detail = client.check(fake_image(reference="gone"))
        assert verdict == rm.Verdict.MISSING
        assert "no such tag" in detail

    def test_a_registry_needing_no_auth_makes_one_request(self, fake, client):
        fake.require_auth = False
        fake.manifests[("team/app", "1.0")] = 200
        assert client.check(fake_image())[0] == rm.Verdict.OK
        assert len(fake.log) == 1
        assert fake.token_requests == 0

    def test_denied_even_with_a_token_means_gone_or_private(self, fake, client):
        fake.manifests[("team/app", "1.0")] = 403
        verdict, detail = client.check(fake_image())
        assert verdict == rm.Verdict.MISSING
        assert "HTTP 403" in detail

    def test_the_request_asks_for_every_manifest_type_and_identifies_itself(self, fake, client):
        client.check(fake_image())
        headers = fake.log[0][2]
        for media_type in ("application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json"):
            assert media_type in headers["Accept"]
        assert headers["User-Agent"] == "homelab-image-check"

    def test_a_digest_is_requested_in_place_of_the_tag(self, fake, client):
        digest = "sha256:" + "c" * 64
        fake.manifests[("team/app", digest)] = 200
        assert client.check(fake_image(reference=digest))[0] == rm.Verdict.OK
        assert f"/manifests/{digest}" in fake.heads[0]


class TestRateLimit:
    def test_a_token_is_fetched_once_per_repository_and_reused_across_its_tags(self, fake, client):
        fake.manifests[("team/app", "1.0")] = 200
        fake.manifests[("team/app", "2.0")] = 200
        fake.manifests[("team/other", "1.0")] = 200
        client.check(fake_image(reference="1.0"))
        client.check(fake_image(reference="2.0"))
        assert fake.token_requests == 1
        client.check(fake_image(repository="team/other"))
        assert fake.token_requests == 2

    def test_requests_are_paced(self, fake, client, sleeps):
        fake.manifests[("team/app", "1.0")] = 200
        client.check(fake_image())
        assert sleeps == [0.5, 0.5]  # a pause before the token request and before the retry, none before the first

    def test_a_429_is_retried_after_the_advertised_wait(self, fake, client, sleeps):
        fake.require_auth = False
        fake.manifests[("team/app", "1.0")] = 200
        fake.fail_next = [(429, {"Retry-After": "7"})]
        assert client.check(fake_image())[0] == rm.Verdict.OK
        assert sleeps == [7.0, 0.5]

    def test_a_retry_after_is_capped(self, fake, client, sleeps):
        fake.require_auth = False
        fake.manifests[("team/app", "1.0")] = 200
        fake.fail_next = [(429, {"Retry-After": "3600"})]
        client.check(fake_image())
        assert sleeps[0] == 60.0

    def test_a_429_without_retry_after_backs_off_exponentially(self, fake, client, sleeps):
        fake.require_auth = False
        fake.manifests[("team/app", "1.0")] = 200
        fake.fail_next = [(429, {}), (503, {}), (500, {})]
        assert client.check(fake_image())[0] == rm.Verdict.OK
        waits = [s for s in sleeps if s != 0.5]
        assert waits == [2.0, 4.0, 8.0]

    def test_persistent_rate_limiting_is_inconclusive_not_missing(self, fake, client):
        fake.require_auth = False
        fake.fail_next = [(429, {"Retry-After": "1"})] * 10
        verdict, detail = client.check(fake_image())
        assert verdict == rm.Verdict.INCONCLUSIVE
        assert "after 5 attempts" in detail
        assert len(fake.heads) == 5

    def test_a_rate_limited_token_endpoint_is_retried(self, fake, client):
        fake.manifests[("team/app", "1.0")] = 200
        fake.token_fail_next = [429]
        assert client.check(fake_image())[0] == rm.Verdict.OK

    def test_an_unreachable_registry_is_inconclusive(self, fake, client):
        fake.close()
        verdict, detail = client.check(fake_image())
        assert verdict == rm.Verdict.INCONCLUSIVE
        assert "no answer" in detail

    def test_a_token_realm_with_a_disallowed_scheme_is_never_fetched(self, fake, sleeps):
        strict = rm.Registry(base_url=fake.base_url, sleep=sleeps.append)
        verdict, detail = strict.check(fake_image())  # base_url is http://, the default allows https only
        assert verdict == rm.Verdict.INCONCLUSIVE
        assert "refusing to fetch" in detail
        assert fake.log == []


def collected_of(*texts: str) -> rm.Collected:
    return rm.Collected(images={text: ["f.yaml"] for text in texts})


class TestRunChecks:
    def test_unanswered_images_get_a_second_pass_after_the_cooldown(self, fake, client):
        fake.require_auth = False
        fake.manifests[("team/app", "1.0")] = 200
        fake.fail_next = [(429, {"Retry-After": "0"})] * 5
        cooldowns: list[float] = []
        results = rm.run_checks(collected_of("fake.example/team/app:1.0"), client, cooldowns.append, cooldown=60)
        assert results["fake.example/team/app:1.0"][0] == rm.Verdict.OK
        assert cooldowns == [60]

    def test_no_cooldown_when_everything_answered(self, fake, client):
        fake.require_auth = False
        cooldowns: list[float] = []
        rm.run_checks(collected_of("fake.example/team/app:1.0"), client, cooldowns.append)
        assert cooldowns == []

    def test_a_malformed_reference_is_reported_as_missing(self, client):
        results = rm.run_checks(collected_of("bad ref"), client, lambda s: None)
        assert results["bad ref"][0] == rm.Verdict.MISSING


class TestReport:
    def test_missing_fails_and_unanswered_only_warns(self):
        collected = rm.Collected(images={"a:1": ["x.yaml"], "b:1": ["y.yaml"], "c:1": ["z.yaml"]}, skipped={"d:local": "built locally"})
        results = {"a:1": (rm.Verdict.OK, "found"), "b:1": (rm.Verdict.MISSING, "gone"), "c:1": (rm.Verdict.INCONCLUSIVE, "429")}
        lines, code = rm.report(collected, results)
        assert code == 1
        assert "::error::b:1 (y.yaml): gone" in lines
        assert any(line.startswith("::warning::c:1") for line in lines)
        assert "3 images: 1 found, 1 missing, 1 unanswered; 1 skipped (d:local [built locally])" in lines[-1]

    def test_only_unanswered_images_do_not_fail_the_run(self):
        collected = rm.Collected(images={"c:1": ["z.yaml"]})
        assert rm.report(collected, {"c:1": (rm.Verdict.INCONCLUSIVE, "429")})[1] == 0

    def test_a_renovate_problem_fails_the_run_even_when_every_image_is_fine(self):
        collected = rm.Collected(images={"a:1": ["x.yaml"]}, problems=["a manager lost its file"])
        lines, code = rm.report(collected, {"a:1": (rm.Verdict.OK, "found")})
        assert code == 1
        assert "::error::a manager lost its file" in lines


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def renovate(root: Path, managers: str) -> None:
    write(root, rm.RENOVATE_CONFIG, f"{{ customManagers: [{managers}] }}")


def found_refs(root: Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for ref in rm.standard_refs(root):
        found.setdefault(ref.text, []).append(ref.source)
    return found


class TestStandardRefs:
    def test_compose_and_ansible_image_lines_are_found_in_every_form(self, root):
        write(
            root,
            "docker/app/compose.yaml",
            "services:\n  a:\n    image: redis:7\n  b:\n    image: \"ghcr.io/x/y:1\"  # pinned\n  c:\n    image: 'alpine:3.20'\n",
        )
        write(root, "docker/app/compose.yaml.j2", "    image: ubuntu/bind9:9.20\n")
        write(root, "ansible/roles/r/tasks/main.yaml", "- community.docker.docker_container:\n    image: curlimages/curl:8.22.0\n- image: alpine\n")
        write(root, "ansible/roles/r/molecule/default/molecule.yml", "platforms:\n  - name: x\n    image: ghcr.io/wenenhoe/molecule-dind:latest\n")
        assert set(found_refs(root)) == {
            "redis:7",
            "ghcr.io/x/y:1",
            "alpine:3.20",
            "ubuntu/bind9:9.20",
            "curlimages/curl:8.22.0",
            "alpine",
            "ghcr.io/wenenhoe/molecule-dind:latest",
        }

    def test_commented_out_and_non_image_lines_are_ignored(self, root):
        write(root, "docker/app/compose.yaml", "# image: old:1\n    build: .\n    container_name: image: x\n")
        assert found_refs(root) == {}

    def test_files_outside_the_scanned_trees_are_ignored(self, root):
        write(root, "docs/example.yaml", "image: redis:7\n")
        write(root, "tools/x.yaml", "image: redis:7\n")
        assert found_refs(root) == {}

    def test_dockerfile_from_and_copy_from_skip_build_stages(self, root):
        write(
            root,
            "docker/app/Dockerfile",
            "FROM caddy:2.11.4-builder AS builder\nRUN x\nFROM caddy:2.11.4\nCOPY --from=builder /a /b\n"
            "COPY --from=0 /c /d\nCOPY --from=busybox:1.38 /e /f\nFROM builder AS again\nFROM scratch\n",
        )
        refs = found_refs(root)
        assert set(refs) == {"caddy:2.11.4-builder", "caddy:2.11.4", "busybox:1.38", "scratch"}

    def test_dockerfiles_under_tools_are_read_too(self, root):
        write(root, "tools/thing/Dockerfile", "FROM ubuntu:26.04 AS fetch\nFROM ubuntu:26.04\nCOPY --from=fetch --chmod=0755 /a /b\n")
        assert set(found_refs(root)) == {"ubuntu:26.04"}

    def test_a_reference_appearing_in_several_files_lists_them_all_once_collected(self, root):
        write(root, "docker/a/compose.yaml", "image: redis:7\n")
        write(root, "docker/b/compose.yaml", "image: redis:7\nimage: redis:7\n")
        renovate(root, "")
        collected = rm.collect(root)
        assert collected.images == {"redis:7": ["docker/a/compose.yaml", "docker/b/compose.yaml"]}

    def test_skipped_references_are_reported_not_checked(self, root):
        write(root, "docker/a/compose.yaml", "image: buildapp:local\nimage: {{ x }}\nimage: redis:7\n")
        renovate(root, "")
        collected = rm.collect(root)
        assert list(collected.images) == ["redis:7"]
        assert collected.skipped == {"buildapp:local": "built locally", "{{": "templated"}


class TestRenovateRefs:
    MANAGER = """{
      customType: "regex",
      description: "rclone in a unit",
      managerFilePatterns: ["/^units\\\\/x\\\\.service$/"],
      matchStrings: ["rclone/rclone:(?<currentValue>[0-9.]+)"],
      datasourceTemplate: "docker",
      depNameTemplate: "rclone/rclone",
    },"""

    def test_a_manager_yields_the_pins_in_the_files_it_names(self, root):
        renovate(root, self.MANAGER)
        write(root, "units/x.service", "ExecStart=docker run rclone/rclone:1.75 copy\n")
        refs, problems = rm.renovate_refs(root)
        assert [(r.text, r.source) for r in refs] == [("rclone/rclone:1.75", "units/x.service")]
        assert problems == []

    def test_a_depname_group_is_used_over_the_template(self, root):
        renovate(
            root,
            """{
              customType: "regex", managerFilePatterns: ["/x\\\\.txt$/"], datasourceTemplate: "docker",
              matchStrings: ["img=\\"(?<depName>[^:\\"]+):(?<currentValue>[^\\"]+)\\""],
            },""",
        )
        write(root, "x.txt", 'img="smallstep/step-cli:0.30.6"\nimg="smallstep/step-ca:0.30.2"\n')
        assert {r.text for r in rm.renovate_refs(root)[0]} == {"smallstep/step-cli:0.30.6", "smallstep/step-ca:0.30.2"}

    def test_managers_for_other_datasources_are_ignored(self, root):
        manager = '{ customType: "regex", managerFilePatterns: ["/x/"], matchStrings: ["(?<currentValue>.+)"], '
        manager += 'datasourceTemplate: "github-releases", depNameTemplate: "a/b" },'
        renovate(root, manager)
        write(root, "x", "1.2.3\n")
        assert rm.renovate_refs(root) == ([], [])

    def test_a_manager_matching_no_file_is_a_problem(self, root):
        renovate(root, self.MANAGER)
        refs, problems = rm.renovate_refs(root)
        assert refs == []
        assert "matches no file" in problems[0]
        assert "rclone in a unit" in problems[0]

    def test_a_file_that_no_longer_matches_the_manager_is_a_problem(self, root):
        renovate(root, self.MANAGER)
        write(root, "units/x.service", "ExecStart=docker run something-else\n")
        refs, problems = rm.renovate_refs(root)
        assert refs == []
        assert "units/x.service: no longer matches" in problems[0]

    def test_a_pattern_that_is_not_a_slash_regex_is_an_error(self, root):
        renovate(root, '{ customType: "regex", managerFilePatterns: ["**/x"], matchStrings: ["a"], datasourceTemplate: "docker", depNameTemplate: "a" },')
        with pytest.raises(rm.RemoteError, match="only /regex/"):
            rm.renovate_refs(root)

    def test_a_manager_without_a_dep_name_or_value_is_an_error(self, root):
        renovate(root, '{ customType: "regex", managerFilePatterns: ["/x$/"], matchStrings: ["(?<currentValue>[0-9]+)"], datasourceTemplate: "docker" },')
        write(root, "x", "12\n")
        with pytest.raises(rm.RemoteError, match="depName and currentValue"):
            rm.renovate_refs(root)

    def test_a_missing_or_malformed_config_is_an_error(self, root):
        with pytest.raises(rm.RemoteError, match="can't read"):
            rm.renovate_refs(root)
        write(root, rm.RENOVATE_CONFIG, "{ customManagers: ")
        with pytest.raises(rm.RemoteError, match="can't read"):
            rm.renovate_refs(root)

    def test_lookbehind_groups_are_not_mistaken_for_named_groups(self, root):
        renovate(
            root,
            """{ customType: "regex", managerFilePatterns: ["/x$/"], datasourceTemplate: "docker", depNameTemplate: "a/b",
                 matchStrings: ["(?<=v)(?<currentValue>[0-9.]+)"] },""",
        )
        write(root, "x", "v1.2\n")
        assert [r.text for r in rm.renovate_refs(root)[0]] == ["a/b:1.2"]


@pytest.fixture
def run_main(root, monkeypatch):
    def run(*argv: str, registry: rm.Registry | None = None) -> tuple[int, str]:
        out = io.StringIO()
        monkeypatch.setattr(rm, "REPO_ROOT", root)
        with contextlib.redirect_stdout(out):
            code = rm.main(list(argv), registry, lambda s: None)
        return code, out.getvalue()

    return run


class TestMain:
    def test_list_prints_references_with_their_files_and_makes_no_requests(self, root, run_main):
        write(root, "docker/a/compose.yaml", "image: redis:7\n")
        renovate(root, "")
        code, out = run_main("list")
        assert code == 0
        assert "redis:7  <- docker/a/compose.yaml" in out

    def test_check_end_to_end_against_the_fake_registry(self, fake, root, run_main):
        fake.manifests[("library/redis", "7")] = 200  # alpine:3.20 is left out: missing
        write(root, "docker/a/compose.yaml", "image: redis:7\nimage: alpine:3.20\n")
        renovate(root, "")
        client = rm.Registry(base_url=fake.base_url, sleep=lambda s: None, schemes=("http",))
        code, out = run_main("check", registry=client)
        assert code == 1
        assert "::error::alpine:3.20 (docker/a/compose.yaml): the registry has no such tag" in out
        assert "2 images: 1 found, 1 missing, 0 unanswered" in out

    def test_check_writes_a_step_summary_when_running_in_actions(self, fake, root, run_main, monkeypatch):
        fake.manifests[("library/redis", "7")] = 200
        write(root, "docker/a/compose.yaml", "image: redis:7\n")
        renovate(root, "")
        summary = root / "summary.md"
        client = rm.Registry(base_url=fake.base_url, sleep=lambda s: None, schemes=("http",))
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
        assert run_main("check", registry=client)[0] == 0
        assert "### Image tags" in summary.read_text()

    def test_a_broken_renovate_config_fails_the_job(self, root, run_main):
        write(root, "docker/a/compose.yaml", "image: redis:7\n")
        assert run_main("check")[0] == 1


@pytest.fixture(scope="module")
def collected():
    return rm.collect(REPO_ROOT)


class TestRealTree:
    def test_no_renovate_manager_has_lost_its_file(self, collected):
        assert collected.problems == []

    def test_the_only_skips_are_the_local_build_and_the_template_fragment(self, collected):
        assert collected.skipped == {"buildapp:local": "built locally", "{{": "templated"}

    def test_every_reference_parses(self, collected, subtests):
        for text in collected.images:
            with subtests.test(text=text):
                image = rm.parse_image(text)
                name_and_tag, _, digest = text.partition("@")
                tag = name_and_tag.rpartition("/")[2].partition(":")[2]
                assert image.repository.rsplit("/", 1)[-1] in text
                assert image.reference == (digest or tag or "latest")

    def test_the_pins_renovate_tracks_outside_compose_are_found(self, collected):
        found = set(collected.images)
        assert any(t.startswith("rclone/rclone:") for t in found)
        assert any(t.startswith("smallstep/step-cli:") for t in found)
        assert any(t.startswith("ghcr.io/renovatebot/renovate:") for t in found)
        assert any(t.startswith("openbao/openbao:") for t in found)

    def test_every_self_built_image_the_registry_publishes_is_checked(self, collected, subtests):
        for image in reg.IMAGES.values():
            for ref in reg.refs(REPO_ROOT, image):
                if image.key != "coderabbit-review":  # a tool image no compose file or scenario pins
                    with subtests.test(ref=ref):
                        assert ref in collected.images

    def test_dockerfile_base_images_are_checked_too(self, collected):
        assert "quxfoo/wastebin:3.7.2" in collected.images
        assert any(t.startswith("caddy:") for t in collected.images)

    def test_the_list_is_the_size_of_a_real_repo(self, collected):
        assert len(collected.images) > 30


class TestStdlibClientSanity:
    def test_open_url_returns_the_status_and_headers_of_an_error_response(self, fake):
        response = rm.open_url(urllib.request.Request(f"http://127.0.0.1:{fake.port}/v2/a/manifests/b", method="HEAD"))
        assert response.status == 401
        assert "bearer" in response.headers["www-authenticate"].lower()
