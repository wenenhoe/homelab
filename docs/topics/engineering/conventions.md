# Conventions

Naming and structural rules that hold across more than one component.
Not a decision record (no fork was weighed — these are patterns
already consistent across the repo) and not a topic doc (no single
component owns them). If a convention here ever needs a real trade-off
made about it, that becomes its own ADR and this doc links to it,
same as [`docs/README.md`](../../README.md) describes for any other topic.

## Naming case: Ansible-world vs Docker/systemd-world

Ansible identifiers — role names (`ansible/roles/*`), most playbook
filenames — are `snake_case`: `backup_agent`, `caddy_cert_expiry`,
`step_ca_cert`. Docker/systemd identifiers — `docker/<app>/` directory
names, compose service names, systemd unit filenames — are
`kebab-case`: `beszel-agent`, `step-ca`, `cloud-sync.timer`. Match the
world you're naming something for, not the file format it happens to
be written in (a `.yaml` playbook is Ansible-world; a `.service.j2`
template's *rendered filename* is systemd-world even though the
template itself lives under an Ansible role).

Known exception: `ansible/playbooks/ci_boot_test.yaml` is snake_case
and hasn't been renamed to match the rest of `playbooks/`.

## Vault KV paths

`secret/data/hosts/<hostname>/<concern>/<name>` mirrors
`host_vars/<hostname>.yaml`; `secret/data/hosts/all/<concern>/<name>`
mirrors `group_vars/all/*.yaml` — see
[ADR 0021](../../decisions/0021-secret-path-layout-for-secrets-with-no-host-owner/revision-000.md)
for why the split follows the inventory structure. Cloud provider
credentials are the one exception, on their own top-level
`secret/data/cloud_credentials/{leaf,rotation}/*` family instead of
under any host, since they anticipate a consumer split
(deploy-only vs. rotation-only identity) that `hosts/*` has no reason
to model — see [ADR 0021](../../decisions/0021-secret-path-layout-for-secrets-with-no-host-owner/revision-000.md)
and [ADR 0023](../../decisions/0023-reusing-cloud-credential-logic-with-the-secrets-store/revision-000.md).

## systemd units

Named for the job they do, not the host or project running it — no
`homelab-` or hostname prefix (`cloud-sync.service`, not
`homelab-cloud-sync.service`). Templated straight to
`/etc/systemd/system/<name>.service` / `.timer` by the owning role
(e.g. `ansible/roles/cloud_sync/templates/cloud-sync.service.j2`), and
every task that writes one pairs it with a `notify: Reload systemd`
handler — a unit file changing without a reload is a real, non-obvious
way for a deploy to silently not take effect. The handler is defined once,
in the `systemd_reload` role; a role that writes units includes that role
(`include_role: {name: systemd_reload}`) before its first `notify` so the
handler exists (see
[`telegram-notifications.md`](../monitoring/telegram-notifications.md#wiring-it-into-this-repo)).

## Telegram topics

One Telegram topic per concern, shared across whichever apps alert
into it (`diun`, Beszel, backups, cert-renewal all route through the
same scheme) rather than one topic per app — see
[ADR 0011](../../decisions/0011-alert-routing-and-noise/revision-000.md) and
[`telegram-notifications.md`](../monitoring/telegram-notifications.md) for the
concern → topic mapping itself.

## Python unit tests

Tests under `ansible/tests/` and `tools/tests/` are written pytest-native
and run with `uv run pytest ansible/tests/ tools/tests/`; the choice is in
[ADR 0069](../../decisions/0069-how-python-unit-tests-are-written-and-run/revision-000.md).

- **Style.** Plain functions or `Test*` classes, plain `assert`, and
  `pytest.raises(..., match=)`. Setup and cleanup are fixtures
  (`tmp_path` and `monkeypatch` before anything hand-rolled), not
  `setUp`, `addCleanup` or a base class. Write no new `TestCase`.
- **Variants.** Cases of one behavior are one
  `@pytest.mark.parametrize` test with an explicit `id`. A loop over data
  read from the real tree at run time, or over cases that must share
  setup a parametrized test would repeat, uses the built-in `subtests`
  fixture (`with subtests.test(...)`), so each case still reports on its
  own. Write no `subTest`.
- **Import roots.** Declared once in `[tool.pytest]` in `pyproject.toml`;
  a test file adds nothing to `sys.path`. A new source directory that
  tests import from is added there. `strict = true` in that table makes
  an unknown option or marker, or a duplicate parametrize id, fail the
  run.
- **Fixtures.** `secrets_dir` (`tools/tests/conftest.py`) points
  `utils.repo.SECRETS_DIR` at an empty directory.
  `fake_vault` (`tools/tests/cloud_credentials/conftest.py`) stands in
  for Vault I/O at the layer `cache.py` reads and writes through;
  `vault` and `rotation_vault` wrap it with `seed()`/`get()`/`delete()`
  defaulting to the `leaf` or `rotation` category.
  `root` is an empty directory standing in for a repository root, defined
  in `tools/tests/doc_scripts/conftest.py` and in
  `tools/tests/ci/conftest.py`.
  `response(status_code, json_body, text)` (`tools/tests/_responses.py`)
  builds a real `requests.Response`; use it wherever the code under test
  reads one, in `tools/tests/`.
  `http_session` is a real `requests.Session` whose network methods are
  autospec'd stand-ins (`stubbed_session()` in `tools/tests/_sessions.py`,
  for a helper that cannot take a fixture); `session_class` also replaces
  `requests.Session` with a class that returns it. A test sets
  `.return_value` on the method it expects the code to call.
  `b2_api` (`tools/tests/cloud_credentials/conftest.py`) is the same for
  b2sdk: a real `B2Api` over an in-memory account with its network calls
  stubbed, and `full_application_key()`, `application_key()` and
  `bucket()` in `_b2_objects.py` build the real key and bucket objects.
  `hvac_client` (`tools/tests/conftest.py`) is a real `hvac.Client` with
  every request stubbed at the adapter and the calls the code makes
  stubbed on top; its `token` starts as `None`, so a `VAULT_TOKEN` in the
  environment never reaches a test.
- **Paths in error messages.** `tmp_path` embeds the test's own name in
  the directory it returns. When the code under test quotes a path in
  an error, create the directory with `tmp_path_factory.mktemp("name")`,
  so a `match=` regex can't pass on the path instead of the message.
- **Test doubles.** A new or changed test chooses a double in this
  order, from
  [ADR 0070](../../decisions/0070-what-a-unit-tests-doubles-are-bound-to/revision-000.md).
  The real object when it builds without I/O (a `requests.Response`, a
  `subprocess.CompletedProcess`, an SDK model object). When the object
  also does I/O (a session, a client, a channel), the real one with only
  its I/O methods replaced by `patch.object(obj, "method", autospec=True)`.
  Otherwise a double bound to the real interface: `autospec=True` on a
  replaced function or method, `create_autospec(Class, instance=True)`
  for an object that cannot be built (a `subprocess.Popen`), and
  `patch("builtins.name", autospec=True)` for a builtin. A bare `Mock` or
  `MagicMock` is only for a value handed back unchanged or a callback.
- **Assertions.** A test ends in an assertion on an outcome the code
  under test decides: a returned value, a raised error, or a side effect
  that happened. Three shapes do not meet that:
  - *No assertion.* A test whose behavior is "does not raise" asserts
    what the code did instead (a value returned, nothing sent), or it
    is not written.
  - *Pass-through.* A test that stubs a collaborator to return a value
    and asserts the code returns it uses a value the code could not
    produce by itself. A stub returning `0` with an assertion on `0`
    still passes when the code hard-codes `0`.
  - *Mock calls only.* A test that asserts only that a mock was called
    asserts the arguments too when it has any
    (`assert_called_once_with`), because the call is the effect under
    test.
- **Inputs.** A test passes the states a caller can produce. A `None` or
  wrong-typed argument to an annotated parameter belongs only where the
  code reads data from outside the program, such as a parsed JSON
  document that is not an object.

## Not yet a convention

AppRole naming has only two real instances so far (`controller`,
`vault-bootstrap`) — not enough to generalize into a rule. Don't infer
a pattern from them; check the actual OpenBao docs for what exists
today.
