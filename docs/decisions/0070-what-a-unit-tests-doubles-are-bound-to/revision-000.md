---
id: ADR-0070
revision: 0
type: adr
title: "What a unit test's doubles are bound to"
solution: "Use the real object with its I/O methods replaced by autospec'd stand-ins; bind every other double to the real interface with autospec; keep bare mocks for sentinels that have no interface"
summary: "What a replaced collaborator in a unit test is bound to, so a test fails when the real interface and the code's use of it disagree."
topic: repository-tooling
status: approved
related: [ADR-0041, ADR-0064, ADR-0069]
---

# 0070. What a unit test's doubles are bound to

## Problem

A unit test that replaces a collaborator (an HTTP response, a subprocess result, an SDK client or model object, a function in another module) has to fail when the code under test uses that collaborator in a way the real one would reject. A double that accepts any attribute and any call lets the test pass while the code is wrong.

## Context

[ADR 0069](../0069-how-python-unit-tests-are-written-and-run/revision-000.md) fixed the suite's style and left test doubles out of scope. [ADR 0064](../0064-where-the-code-behind-ci-and-documentation-checks-lives/revision-000.md) requires the code behind CI and cloud-credential tooling to be unit-tested, and much of that code talks to `requests`, `subprocess`, `hvac`, `paramiko`, B2 and OCI.

Measured on `main` when this was written, across `ansible/tests/` and `tools/tests/`:

- 146 `Mock`, `MagicMock`, `AsyncMock` or `NonCallableMock` constructions, 9 of them with `spec` or `spec_set`.
- 325 `patch` and `patch.object` calls, none with `autospec` or `spec`; 23 of them pass `new=` or `new_callable`, which `autospec` cannot be combined with.

Run against the locked Python 3.14.4:

- `unittest.mock.patch` without `autospec` accepts a call with the wrong number of arguments; with `autospec=True` the same call raises `TypeError`.
- `Mock(spec=requests.Response)` has no `status_code`, `Mock(spec=subprocess.CompletedProcess)` has no `returncode`, and `Mock(spec=ApplicationKey)` from b2sdk has no `expiration_timestamp_millis`, because each is set in `__init__` rather than on the class. `create_autospec(..., instance=True)` behaves the same, so a spec'd double either cannot return the field the code reads or has it assigned by the test, which defeats the binding. `Mock(spec_set=...)` refuses the assignment.
- `requests.Response()`, `subprocess.CompletedProcess(...)`, b2sdk `ApplicationKey(...)` and `oci.identity.models.ApiKey()` construct without I/O.

A throwaway run forced `autospec=True` onto every `patch` that can take it, without editing a test. Of the 325, 302 are eligible; the other 23 pass `new=` or `new_callable`. 1,940 tests still passed and 21 failed, for two reasons and no others:

- 18 failed because the patched class's instances read an attribute set in `__init__`: `requests.Session.headers` and the `session` of a b2sdk `B2Api`. An autospec'd class cannot provide either.
- 3 failed because `patch.object(module, "input")` reaches a builtin through a module namespace, where `mock` forces `create=True` and refuses `autospec`. The 4 existing `patch("builtins.input", ...)` calls take `autospec=True` without trouble.

No flip showed a call the real signature rejects, so the first pass changes no code under test.

With every socket connection blocked, each stand-in the suite uses builds offline and takes autospec'd replacements for its I/O methods:

- `requests.Session` and `requests.Response` (body set on the response, `raise_for_status` raising on a 403).
- `subprocess.CompletedProcess`.
- b2sdk `B2Api(InMemoryAccountInfo())`, `FullApplicationKey`, `ApplicationKey` and `Bucket`.
- `hvac.Client`.
- paramiko `SSHClient`, `Channel` and `ChannelFile`.
- OCI `identity_domains` models and `oci.response.Response`, and the `IdentityDomainsClient` that `identity_domains_client_for_token` already builds in the repo.

The suite's other doubles are replacements for functions in this repo, which autospec binds without I/O, and a few opaque values handed through unchanged. OCI's `IdentityDomainsClient` methods take `**kwargs`, so autospec accepts any keyword there.

[ADR 0041](../0041-testing-the-oci-classic-iam-bootstrap/revision-000.md), still `working`, covers a different slice: it asks how the OCI classic-IAM bootstrap is tested beyond hand-written mocks, and keeps the SCIM tests hand-mocked. This record governs what any hand-written double is bound to, including those.

## Decision

A double is chosen in this order.

1. **The real object**, when it builds without I/O: a `requests.Response`, a `subprocess.CompletedProcess`, an SDK model object. When the object also does I/O, such as a `requests.Session`, an SDK client or a paramiko channel, the test builds the real one and replaces only its I/O methods with `patch.object(obj, "method", autospec=True)`. A test builds the object through a small shared factory in a `conftest.py` or helper module when more than one test needs it. A real object cannot drift from the real interface, and it keeps the fields set in `__init__` that code reads.
2. **A double bound to the real interface**, for a replaced function or for a collaborator with no cheap constructor: `patch(..., autospec=True)` or `patch.object(..., autospec=True)`, and `create_autospec(fn, return_value=...)` for a function placed with `monkeypatch.setattr`. A call the real signature would reject then fails the test. A builtin is patched as `patch("builtins.name", autospec=True)`, not through a module that does not define it.
3. **A bare `Mock` or `MagicMock`**, only where there is no interface to bind to: a sentinel the code under test must hand back unchanged, or a callback it receives. A bare mock standing in for a client, session, response or process is not covered by this case.

A `spec` or `spec_set` on a class is not a substitute for step 1: it hides the fields a real object sets in `__init__`.

A `patch` that passes `new=` or `new_callable` takes the replacement from the caller, so the caller passes an object that follows steps 1 to 3 rather than a bare one.

Existing doubles are brought into line case by case, in separate changes on the converted files. A flip that makes a test fail is one of two things. If the real signature rejects the call, the fix goes in the same change, on whichever side is wrong. If the code reads an attribute that autospec cannot see, step 1 answers it. No test is skipped or loosened to make a flip pass.

## Alternatives considered

- **`autospec=True` on every `patch` in one change.** Mechanical and quick, but a test that fails afterwards cannot be told apart from collateral damage in a large diff, so each real mismatch is lost in it. It also cannot apply to the 23 `new=` or `new_callable` calls.
- **`spec` or `spec_set` on every `Mock`.** Cheaper than a factory, but it hides fields set in `__init__` (above), so the double either lacks what the code reads or has it assigned by the test.
- **A local emulator for every external service.** The closest stand-in for real behavior, and [ADR 0041](../0041-testing-the-oci-classic-iam-bootstrap/revision-000.md) is evaluating it for one surface. As a rule for every collaborator it adds a service per SDK and moves the tests out of unit scope.
- **Contract tests against the real services.** They need network access and credentials, so they are not unit tests and cannot run in `pr-checks.yml` without them.
- **`pytest-mock`.** Rejected in [ADR 0069](../0069-how-python-unit-tests-are-written-and-run/revision-000.md): its `mocker` fixture adds a package and does nothing `monkeypatch` and `unittest.mock.patch` don't.

## Consequences

- Some tests fail on the first flip and need a code or test fix. Each pass is therefore its own change, not a bulk edit.
- A shared factory per collaborator type is new test-support code to keep in step with the SDKs; it lives with the tests, and the conventions in [`docs/topics/engineering/conventions.md`](../../topics/engineering/conventions.md) list it once it exists.
- Tests that read a field of a real object set it explicitly, so a test shows which fields the code depends on.
- Autospec binds a double to the real signature and no further. Where an SDK method takes `**kwargs`, as OCI's do, the test's assertion on the call's arguments is what pins them.

## Invariants

- No new bare `Mock` or `MagicMock` stands in for an object that has a real interface.
- No `patch` of a function or method omits `autospec` unless it passes `new=` or `new_callable`, and a `new=` replacement follows steps 1 to 3.
- A test never loosens a double's binding to make a test pass.

## Non-goals

- What a test must assert, and which tests are deleted or merged. Those rules go in `conventions.md` and stand independently of how a double is built.
- Mutation testing; a spike answers whether it adds signal before any decision.
- Which behaviors get a test, and Molecule scenarios, which [`molecule-testing.md`](../../topics/engineering/molecule-testing.md) covers.
- Replacing hand-written doubles with an emulator for the OCI classic-IAM surface, which is [ADR 0041](../0041-testing-the-oci-classic-iam-bootstrap/revision-000.md).

## Reconsideration triggers

- A standard-library `unittest.mock` change in how `spec`, `autospec` or `create_autospec` treat fields set in `__init__`.
- ADR 0041 is accepted with an emulator the other SDKs can also use.
