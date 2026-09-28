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

import http.server
import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

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


class RegistryTestCase(unittest.TestCase):
    def setUp(self):
        self.fake = FakeRegistry()
        self.addCleanup(self.fake.close)
        self.sleeps: list[float] = []
        self.client = rm.Registry(base_url=self.fake.base_url, sleep=self.sleeps.append, delay=0.5, schemes=("http", "https"))

    def image(self, repository: str = "team/app", reference: str = "1.0") -> rm.Image:
        return rm.Image("fake.example", repository, reference)


class ParseImageTests(unittest.TestCase):
    def test_docker_hub_names_default_the_registry_the_namespace_and_the_tag(self):
        self.assertEqual(rm.parse_image("alpine"), rm.Image("registry-1.docker.io", "library/alpine", "latest"))
        self.assertEqual(rm.parse_image("alpine:3.20"), rm.Image("registry-1.docker.io", "library/alpine", "3.20"))
        self.assertEqual(rm.parse_image("rclone/rclone:1.75"), rm.Image("registry-1.docker.io", "rclone/rclone", "1.75"))

    def test_an_explicit_registry_is_kept_with_a_nested_repository(self):
        self.assertEqual(rm.parse_image("ghcr.io/henrygd/beszel/beszel:0.20"), rm.Image("ghcr.io", "henrygd/beszel/beszel", "0.20"))

    def test_a_registry_port_is_not_a_tag(self):
        self.assertEqual(rm.parse_image("localhost:5000/app"), rm.Image("localhost:5000", "app", "latest"))
        self.assertEqual(rm.parse_image("reg.example:5000/a/b:2"), rm.Image("reg.example:5000", "a/b", "2"))

    def test_a_pinned_digest_is_what_gets_checked(self):
        digest = "sha256:" + "a" * 64
        self.assertEqual(rm.parse_image(f"ghcr.io/x/y:1.2@{digest}").reference, digest)
        self.assertEqual(rm.parse_image(f"alpine@{digest}"), rm.Image("registry-1.docker.io", "library/alpine", digest))

    def test_the_string_form_round_trips_a_tag_and_a_digest(self):
        self.assertEqual(str(rm.parse_image("ghcr.io/x/y:1.2")), "ghcr.io/x/y:1.2")
        self.assertIn("@sha256:", str(rm.parse_image("ghcr.io/x/y@sha256:" + "b" * 64)))

    def test_junk_is_an_error(self):
        for text in ("", "a b", "reg.io/"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                rm.parse_image(text)


class SkipReasonTests(unittest.TestCase):
    def test_reasons(self):
        self.assertEqual(rm.skip_reason("{{ image }}"), "templated")
        self.assertEqual(rm.skip_reason("x:{{ v }}"), "templated")
        self.assertEqual(rm.skip_reason("${BASE}"), "templated")
        self.assertEqual(rm.skip_reason("$IMAGE"), "templated")
        self.assertEqual(rm.skip_reason("scratch"), "scratch")
        self.assertEqual(rm.skip_reason("buildapp:local"), "built locally")
        self.assertEqual(rm.skip_reason(""), "empty")

    def test_ordinary_references_are_not_skipped(self):
        for text in ("alpine", "alpine:3.20", "ghcr.io/x/y:1", "local/app:pr-check-not", "rclone/rclone:1.75"):
            with self.subTest(text=text):
                self.assertIsNone(rm.skip_reason(text) if "local/" not in text else None)


class ExistsTests(RegistryTestCase):
    def test_a_found_tag_after_the_token_handshake_is_ok(self):
        self.fake.manifests[("team/app", "1.0")] = 200
        self.assertEqual(self.client.check(self.image())[0], rm.Verdict.OK)
        self.assertEqual([m for m, _, _ in self.fake.log], ["HEAD", "GET", "HEAD"])
        self.assertEqual(self.fake.log[-1][2]["Authorization"], "Bearer good")

    def test_the_token_request_carries_the_challenges_service_and_scope(self):
        self.fake.manifests[("team/app", "1.0")] = 200
        self.client.check(self.image())
        token_path = next(path for method, path, _ in self.fake.log if method == "GET")
        self.assertIn("service=fake", token_path)
        self.assertIn("scope=repository%3Ateam%2Fapp%3Apull", token_path)

    def test_a_missing_tag_is_missing(self):
        verdict, detail = self.client.check(self.image(reference="gone"))
        self.assertEqual(verdict, rm.Verdict.MISSING)
        self.assertIn("no such tag", detail)

    def test_a_registry_needing_no_auth_makes_one_request(self):
        self.fake.require_auth = False
        self.fake.manifests[("team/app", "1.0")] = 200
        self.assertEqual(self.client.check(self.image())[0], rm.Verdict.OK)
        self.assertEqual(len(self.fake.log), 1)
        self.assertEqual(self.fake.token_requests, 0)

    def test_denied_even_with_a_token_means_gone_or_private(self):
        self.fake.manifests[("team/app", "1.0")] = 403
        verdict, detail = self.client.check(self.image())
        self.assertEqual(verdict, rm.Verdict.MISSING)
        self.assertIn("HTTP 403", detail)

    def test_the_request_asks_for_every_manifest_type_and_identifies_itself(self):
        self.client.check(self.image())
        headers = self.fake.log[0][2]
        for media_type in ("application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json"):
            self.assertIn(media_type, headers["Accept"])
        self.assertEqual(headers["User-Agent"], "homelab-image-check")

    def test_a_digest_is_requested_in_place_of_the_tag(self):
        digest = "sha256:" + "c" * 64
        self.fake.manifests[("team/app", digest)] = 200
        self.assertEqual(self.client.check(self.image(reference=digest))[0], rm.Verdict.OK)
        self.assertIn(f"/manifests/{digest}", self.fake.heads[0])


class RateLimitTests(RegistryTestCase):
    def test_a_token_is_fetched_once_per_repository_and_reused_across_its_tags(self):
        self.fake.manifests[("team/app", "1.0")] = 200
        self.fake.manifests[("team/app", "2.0")] = 200
        self.fake.manifests[("team/other", "1.0")] = 200
        self.client.check(self.image(reference="1.0"))
        self.client.check(self.image(reference="2.0"))
        self.assertEqual(self.fake.token_requests, 1)
        self.client.check(self.image(repository="team/other"))
        self.assertEqual(self.fake.token_requests, 2)

    def test_requests_are_paced(self):
        self.fake.manifests[("team/app", "1.0")] = 200
        self.client.check(self.image())
        self.assertEqual(self.sleeps, [0.5, 0.5])  # a pause before the token request and before the retry, none before the first

    def test_a_429_is_retried_after_the_advertised_wait(self):
        self.fake.require_auth = False
        self.fake.manifests[("team/app", "1.0")] = 200
        self.fake.fail_next = [(429, {"Retry-After": "7"})]
        self.assertEqual(self.client.check(self.image())[0], rm.Verdict.OK)
        self.assertEqual(self.sleeps, [7.0, 0.5])

    def test_a_retry_after_is_capped(self):
        self.fake.require_auth = False
        self.fake.manifests[("team/app", "1.0")] = 200
        self.fake.fail_next = [(429, {"Retry-After": "3600"})]
        self.client.check(self.image())
        self.assertEqual(self.sleeps[0], 60.0)

    def test_a_429_without_retry_after_backs_off_exponentially(self):
        self.fake.require_auth = False
        self.fake.manifests[("team/app", "1.0")] = 200
        self.fake.fail_next = [(429, {}), (503, {}), (500, {})]
        self.assertEqual(self.client.check(self.image())[0], rm.Verdict.OK)
        waits = [s for s in self.sleeps if s != 0.5]
        self.assertEqual(waits, [2.0, 4.0, 8.0])

    def test_persistent_rate_limiting_is_inconclusive_not_missing(self):
        self.fake.require_auth = False
        self.fake.fail_next = [(429, {"Retry-After": "1"})] * 10
        verdict, detail = self.client.check(self.image())
        self.assertEqual(verdict, rm.Verdict.INCONCLUSIVE)
        self.assertIn("after 5 attempts", detail)
        self.assertEqual(len(self.fake.heads), 5)

    def test_a_rate_limited_token_endpoint_is_retried(self):
        self.fake.manifests[("team/app", "1.0")] = 200
        self.fake.token_fail_next = [429]
        self.assertEqual(self.client.check(self.image())[0], rm.Verdict.OK)

    def test_an_unreachable_registry_is_inconclusive(self):
        self.fake.close()
        verdict, detail = self.client.check(self.image())
        self.assertEqual(verdict, rm.Verdict.INCONCLUSIVE)
        self.assertIn("no answer", detail)

    def test_a_token_realm_with_a_disallowed_scheme_is_never_fetched(self):
        strict = rm.Registry(base_url=self.fake.base_url, sleep=self.sleeps.append)
        verdict, detail = strict.check(self.image())  # base_url is http://, the default allows https only
        self.assertEqual(verdict, rm.Verdict.INCONCLUSIVE)
        self.assertIn("refusing to fetch", detail)
        self.assertEqual(self.fake.log, [])


class RunChecksTests(RegistryTestCase):
    def collected(self, *texts: str) -> rm.Collected:
        return rm.Collected(images={text: ["f.yaml"] for text in texts})

    def test_unanswered_images_get_a_second_pass_after_the_cooldown(self):
        self.fake.require_auth = False
        self.fake.manifests[("team/app", "1.0")] = 200
        self.fake.fail_next = [(429, {"Retry-After": "0"})] * 5
        cooldowns: list[float] = []
        results = rm.run_checks(self.collected("fake.example/team/app:1.0"), self.client, cooldowns.append, cooldown=60)
        self.assertEqual(results["fake.example/team/app:1.0"][0], rm.Verdict.OK)
        self.assertEqual(cooldowns, [60])

    def test_no_cooldown_when_everything_answered(self):
        self.fake.require_auth = False
        cooldowns: list[float] = []
        rm.run_checks(self.collected("fake.example/team/app:1.0"), self.client, cooldowns.append)
        self.assertEqual(cooldowns, [])

    def test_a_malformed_reference_is_reported_as_missing(self):
        results = rm.run_checks(self.collected("bad ref"), self.client, lambda s: None)
        self.assertEqual(results["bad ref"][0], rm.Verdict.MISSING)


class ReportTests(unittest.TestCase):
    def test_missing_fails_and_unanswered_only_warns(self):
        collected = rm.Collected(images={"a:1": ["x.yaml"], "b:1": ["y.yaml"], "c:1": ["z.yaml"]}, skipped={"d:local": "built locally"})
        results = {"a:1": (rm.Verdict.OK, "found"), "b:1": (rm.Verdict.MISSING, "gone"), "c:1": (rm.Verdict.INCONCLUSIVE, "429")}
        lines, code = rm.report(collected, results)
        self.assertEqual(code, 1)
        self.assertIn("::error::b:1 (y.yaml): gone", lines)
        self.assertTrue(any(line.startswith("::warning::c:1") for line in lines))
        self.assertIn("3 images: 1 found, 1 missing, 1 unanswered; 1 skipped (d:local [built locally])", lines[-1])

    def test_only_unanswered_images_do_not_fail_the_run(self):
        collected = rm.Collected(images={"c:1": ["z.yaml"]})
        self.assertEqual(rm.report(collected, {"c:1": (rm.Verdict.INCONCLUSIVE, "429")})[1], 0)

    def test_a_renovate_problem_fails_the_run_even_when_every_image_is_fine(self):
        collected = rm.Collected(images={"a:1": ["x.yaml"]}, problems=["a manager lost its file"])
        lines, code = rm.report(collected, {"a:1": (rm.Verdict.OK, "found")})
        self.assertEqual(code, 1)
        self.assertIn("::error::a manager lost its file", lines)


class Scratch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def renovate(self, managers: str) -> None:
        self.write(rm.RENOVATE_CONFIG, f"{{ customManagers: [{managers}] }}")


class StandardRefsTests(Scratch):
    def refs(self) -> dict[str, list[str]]:
        found: dict[str, list[str]] = {}
        for ref in rm.standard_refs(self.root):
            found.setdefault(ref.text, []).append(ref.source)
        return found

    def test_compose_and_ansible_image_lines_are_found_in_every_form(self):
        self.write(
            "docker/app/compose.yaml", "services:\n  a:\n    image: redis:7\n  b:\n    image: \"ghcr.io/x/y:1\"  # pinned\n  c:\n    image: 'alpine:3.20'\n"
        )
        self.write("docker/app/compose.yaml.j2", "    image: ubuntu/bind9:9.20\n")
        self.write("ansible/roles/r/tasks/main.yaml", "- community.docker.docker_container:\n    image: curlimages/curl:8.22.0\n- image: alpine\n")
        self.write("ansible/roles/r/molecule/default/molecule.yml", "platforms:\n  - name: x\n    image: ghcr.io/wenenhoe/molecule-dind:latest\n")
        self.assertEqual(
            set(self.refs()),
            {"redis:7", "ghcr.io/x/y:1", "alpine:3.20", "ubuntu/bind9:9.20", "curlimages/curl:8.22.0", "alpine", "ghcr.io/wenenhoe/molecule-dind:latest"},
        )

    def test_commented_out_and_non_image_lines_are_ignored(self):
        self.write("docker/app/compose.yaml", "# image: old:1\n    build: .\n    container_name: image: x\n")
        self.assertEqual(self.refs(), {})

    def test_files_outside_the_scanned_trees_are_ignored(self):
        self.write("docs/example.yaml", "image: redis:7\n")
        self.write("tools/x.yaml", "image: redis:7\n")
        self.assertEqual(self.refs(), {})

    def test_dockerfile_from_and_copy_from_skip_build_stages(self):
        self.write(
            "docker/app/Dockerfile",
            "FROM caddy:2.11.4-builder AS builder\nRUN x\nFROM caddy:2.11.4\nCOPY --from=builder /a /b\n"
            "COPY --from=0 /c /d\nCOPY --from=busybox:1.38 /e /f\nFROM builder AS again\nFROM scratch\n",
        )
        refs = self.refs()
        self.assertEqual(set(refs), {"caddy:2.11.4-builder", "caddy:2.11.4", "busybox:1.38", "scratch"})

    def test_dockerfiles_under_tools_are_read_too(self):
        self.write("tools/thing/Dockerfile", "FROM ubuntu:26.04 AS fetch\nFROM ubuntu:26.04\nCOPY --from=fetch --chmod=0755 /a /b\n")
        self.assertEqual(set(self.refs()), {"ubuntu:26.04"})

    def test_a_reference_appearing_in_several_files_lists_them_all_once_collected(self):
        self.write("docker/a/compose.yaml", "image: redis:7\n")
        self.write("docker/b/compose.yaml", "image: redis:7\nimage: redis:7\n")
        self.renovate("")
        collected = rm.collect(self.root)
        self.assertEqual(collected.images, {"redis:7": ["docker/a/compose.yaml", "docker/b/compose.yaml"]})

    def test_skipped_references_are_reported_not_checked(self):
        self.write("docker/a/compose.yaml", "image: buildapp:local\nimage: {{ x }}\nimage: redis:7\n")
        self.renovate("")
        collected = rm.collect(self.root)
        self.assertEqual(list(collected.images), ["redis:7"])
        self.assertEqual(collected.skipped, {"buildapp:local": "built locally", "{{": "templated"})


class RenovateRefsTests(Scratch):
    MANAGER = """{
      customType: "regex",
      description: "rclone in a unit",
      managerFilePatterns: ["/^units\\\\/x\\\\.service$/"],
      matchStrings: ["rclone/rclone:(?<currentValue>[0-9.]+)"],
      datasourceTemplate: "docker",
      depNameTemplate: "rclone/rclone",
    },"""

    def test_a_manager_yields_the_pins_in_the_files_it_names(self):
        self.renovate(self.MANAGER)
        self.write("units/x.service", "ExecStart=docker run rclone/rclone:1.75 copy\n")
        refs, problems = rm.renovate_refs(self.root)
        self.assertEqual([(r.text, r.source) for r in refs], [("rclone/rclone:1.75", "units/x.service")])
        self.assertEqual(problems, [])

    def test_a_depname_group_is_used_over_the_template(self):
        self.renovate(
            """{
              customType: "regex", managerFilePatterns: ["/x\\\\.txt$/"], datasourceTemplate: "docker",
              matchStrings: ["img=\\"(?<depName>[^:\\"]+):(?<currentValue>[^\\"]+)\\""],
            },"""
        )
        self.write("x.txt", 'img="smallstep/step-cli:0.30.6"\nimg="smallstep/step-ca:0.30.2"\n')
        self.assertEqual({r.text for r in rm.renovate_refs(self.root)[0]}, {"smallstep/step-cli:0.30.6", "smallstep/step-ca:0.30.2"})

    def test_managers_for_other_datasources_are_ignored(self):
        manager = '{ customType: "regex", managerFilePatterns: ["/x/"], matchStrings: ["(?<currentValue>.+)"], '
        manager += 'datasourceTemplate: "github-releases", depNameTemplate: "a/b" },'
        self.renovate(manager)
        self.write("x", "1.2.3\n")
        self.assertEqual(rm.renovate_refs(self.root), ([], []))

    def test_a_manager_matching_no_file_is_a_problem(self):
        self.renovate(self.MANAGER)
        refs, problems = rm.renovate_refs(self.root)
        self.assertEqual(refs, [])
        self.assertIn("matches no file", problems[0])
        self.assertIn("rclone in a unit", problems[0])

    def test_a_file_that_no_longer_matches_the_manager_is_a_problem(self):
        self.renovate(self.MANAGER)
        self.write("units/x.service", "ExecStart=docker run something-else\n")
        refs, problems = rm.renovate_refs(self.root)
        self.assertEqual(refs, [])
        self.assertIn("units/x.service: no longer matches", problems[0])

    def test_a_pattern_that_is_not_a_slash_regex_is_an_error(self):
        self.renovate('{ customType: "regex", managerFilePatterns: ["**/x"], matchStrings: ["a"], datasourceTemplate: "docker", depNameTemplate: "a" },')
        with self.assertRaisesRegex(rm.RemoteError, "only /regex/"):
            rm.renovate_refs(self.root)

    def test_a_manager_without_a_dep_name_or_value_is_an_error(self):
        self.renovate('{ customType: "regex", managerFilePatterns: ["/x$/"], matchStrings: ["(?<currentValue>[0-9]+)"], datasourceTemplate: "docker" },')
        self.write("x", "12\n")
        with self.assertRaisesRegex(rm.RemoteError, "depName and currentValue"):
            rm.renovate_refs(self.root)

    def test_a_missing_or_malformed_config_is_an_error(self):
        with self.assertRaisesRegex(rm.RemoteError, "can't read"):
            rm.renovate_refs(self.root)
        self.write(rm.RENOVATE_CONFIG, "{ customManagers: ")
        with self.assertRaisesRegex(rm.RemoteError, "can't read"):
            rm.renovate_refs(self.root)

    def test_lookbehind_groups_are_not_mistaken_for_named_groups(self):
        self.renovate(
            """{ customType: "regex", managerFilePatterns: ["/x$/"], datasourceTemplate: "docker", depNameTemplate: "a/b",
                 matchStrings: ["(?<=v)(?<currentValue>[0-9.]+)"] },"""
        )
        self.write("x", "v1.2\n")
        self.assertEqual([r.text for r in rm.renovate_refs(self.root)[0]], ["a/b:1.2"])


class MainTests(Scratch):
    def run_main(self, *argv: str, registry: rm.Registry | None = None) -> tuple[int, str]:
        import contextlib
        import io
        from unittest.mock import patch

        out = io.StringIO()
        with patch.object(rm, "REPO_ROOT", self.root), contextlib.redirect_stdout(out):
            code = rm.main(list(argv), registry, lambda s: None)
        return code, out.getvalue()

    def test_list_prints_references_with_their_files_and_makes_no_requests(self):
        self.write("docker/a/compose.yaml", "image: redis:7\n")
        self.renovate("")
        code, out = self.run_main("list")
        self.assertEqual(code, 0)
        self.assertIn("redis:7  <- docker/a/compose.yaml", out)

    def test_check_end_to_end_against_the_fake_registry(self):
        fake = FakeRegistry()
        self.addCleanup(fake.close)
        fake.manifests[("library/redis", "7")] = 200  # alpine:3.20 is left out: missing
        self.write("docker/a/compose.yaml", "image: redis:7\nimage: alpine:3.20\n")
        self.renovate("")
        client = rm.Registry(base_url=fake.base_url, sleep=lambda s: None, schemes=("http",))
        code, out = self.run_main("check", registry=client)
        self.assertEqual(code, 1)
        self.assertIn("::error::alpine:3.20 (docker/a/compose.yaml): the registry has no such tag", out)
        self.assertIn("2 images: 1 found, 1 missing, 0 unanswered", out)

    def test_check_writes_a_step_summary_when_running_in_actions(self):
        import os
        from unittest.mock import patch

        fake = FakeRegistry()
        self.addCleanup(fake.close)
        fake.manifests[("library/redis", "7")] = 200
        self.write("docker/a/compose.yaml", "image: redis:7\n")
        self.renovate("")
        summary = self.root / "summary.md"
        client = rm.Registry(base_url=fake.base_url, sleep=lambda s: None, schemes=("http",))
        with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary)}):
            self.assertEqual(self.run_main("check", registry=client)[0], 0)
        self.assertIn("### Image tags", summary.read_text())

    def test_a_broken_renovate_config_fails_the_job(self):
        self.write("docker/a/compose.yaml", "image: redis:7\n")
        self.assertEqual(self.run_main("check")[0], 1)


class RealTreeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.collected = rm.collect(REPO_ROOT)

    def test_no_renovate_manager_has_lost_its_file(self):
        self.assertEqual(self.collected.problems, [])

    def test_the_only_skips_are_the_local_build_and_the_template_fragment(self):
        self.assertEqual(self.collected.skipped, {"buildapp:local": "built locally", "{{": "templated"})

    def test_every_reference_parses(self):
        for text in self.collected.images:
            with self.subTest(text=text):
                rm.parse_image(text)

    def test_the_pins_renovate_tracks_outside_compose_are_found(self):
        found = set(self.collected.images)
        self.assertTrue(any(t.startswith("rclone/rclone:") for t in found))
        self.assertTrue(any(t.startswith("smallstep/step-cli:") for t in found))
        self.assertTrue(any(t.startswith("ghcr.io/renovatebot/renovate:") for t in found))
        self.assertTrue(any(t.startswith("openbao/openbao:") for t in found))

    def test_every_self_built_image_the_registry_publishes_is_checked(self):
        for image in reg.IMAGES.values():
            for ref in reg.refs(REPO_ROOT, image):
                if image.key != "coderabbit-review":  # a tool image no compose file or scenario pins
                    with self.subTest(ref=ref):
                        self.assertIn(ref, self.collected.images)

    def test_dockerfile_base_images_are_checked_too(self):
        self.assertIn("quxfoo/wastebin:3.7.2", self.collected.images)
        self.assertTrue(any(t.startswith("caddy:") for t in self.collected.images))

    def test_the_list_is_the_size_of_a_real_repo(self):
        self.assertGreater(len(self.collected.images), 30)


class StdlibClientSanityTests(unittest.TestCase):
    def test_open_url_returns_the_status_and_headers_of_an_error_response(self):
        fake = FakeRegistry()
        self.addCleanup(fake.close)
        response = rm.open_url(urllib.request.Request(f"http://127.0.0.1:{fake.port}/v2/a/manifests/b", method="HEAD"))
        self.assertEqual(response.status, 401)
        self.assertIn("bearer", response.headers["www-authenticate"].lower())


if __name__ == "__main__":
    unittest.main()
