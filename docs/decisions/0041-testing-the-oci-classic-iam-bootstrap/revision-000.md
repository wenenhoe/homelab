---
id: ADR-0041
revision: 0
type: adr
title: Testing the OCI classic-IAM bootstrap
solution: floci-oci for the classic-IAM surface only; SCIM tests stay hand-mocked
summary: How the OCI classic-IAM bootstrap code is tested beyond hand-written mocks.
topic: repository-tooling
status: working
related: [ADR-0016]
---

# floci-oci for OCI classic-IAM bootstrap tests; SCIM leaf tests stay hand-mocked

## Context

`tools/cloud_credentials/` talks to OCI through two unrelated auth
surfaces (see `rotation_keys/oci_scim.py`'s own header comment and ADR
0016):

- **Classic Signature V1** (`rotation_keys/oci_iam.py`,
  `rotation_keys/oci_bootstrap.py`) — a `requests.Session` signed by
  `oci.signer.Signer`, hitting `/20160918/{users,groups,
  userGroupMemberships,policies}` on `identity.<region>.oraclecloud.com`
  directly. Used once, by a human, for rotation-key bootstrap.
- **Identity Domains SCIM** (`leaf_keys/oci.py`, `oci_scim.py`,
  `check_freshness.py`) — OAuth2 client-credentials against
  `<domain>/oauth2/v1/token`, then `oci.identity_domains
  .IdentityDomainsClient` calls using the `customerSecretKey` schema.
  This is the surface every quarterly leaf rotation and freshness check
  actually exercises.

Both are currently tested the same way: `unittest.mock.MagicMock`
standing in for the SDK client or the `requests.Session`
(`tools/tests/cloud_credentials/leaf_keys/test_oci.py`,
`rotation_keys/test_oci_bootstrap.py`, `test_oci_scim.py`) — assertions
on call args, no real HTTP wire behavior exercised.

[floci-oci](https://github.com/floci-io/floci-oci) is a local OCI
emulator (Docker image, port 4599) claiming real OCI wire protocols —
`opc-request-id`, `etag`/`if-match`, exact error bodies — validated by
its own SDK/CLI/Terraform compatibility suite. Its
[services overview](https://floci.io/floci-oci/services/) lists
Identity (IAM) coverage as `/20160918/…`: compartments, users, groups,
memberships, policies — the exact path prefix and resource set
`oci_iam.py`/`oci_bootstrap.py` call. Its own README is explicit,
though, that **Identity Domains is not implemented**: "Not implemented
yet: identity domains, API keys/auth tokens, dynamic groups, tag
namespaces, …". There is no path to exercising the SCIM
`customerSecretKey` flow — the surface this repo's tests spend the
most effort on — against floci-oci at all; it isn't a maturity gap
that might close soon, it's a different, unimplemented service.

The project itself is young: MIT-licensed, v0.1.x, 2 GitHub stars, no
production track record to lean on beyond its own compatibility suite.

## Decision

Adopt floci-oci, scoped narrowly to the classic-IAM surface only:
`oci_iam.py` and the non-SCIM half of `oci_bootstrap.py`
(`oci_ensure_leaf_identity`, user/group/membership/policy creation).
Run it as a Docker service in the `python-unit-tests` job, alongside —
not replacing — the existing `MagicMock`-based tests for that module,
until the spike below shows whether floci-oci's request/response shape
actually lets today's assertions (e.g. exact policy `statements` body)
pass unmodified.

Do not adopt it for `leaf_keys/oci.py`, `oci_scim.py`, or
`check_freshness.py`'s OCI path — nothing to point it at, since
Identity Domains isn't implemented. Those stay on `MagicMock` as-is.
Revisit this half only if floci-oci ships Identity Domains support;
until then there's nothing to re-evaluate.

## Assumptions

- **Claim:** floci-oci's `/20160918/…` Identity emulation is faithful
  enough for `oci_bootstrap.py`'s actual call shapes — in particular,
  that `oci_get_or_create_user`'s 409-on-exists fallback to
  `oci_lookup_one`, and `policies`' statement-array PUT
  (`oci_bootstrap.py:101`), behave the way this code's `except
  requests.HTTPError` branches assume.
  **Breaks if wrong:** the existing hand-written `MagicMock` tests stay
  the only coverage for this module; floci-oci adds a CI dependency
  (Docker pull, container startup) without adding real assurance.
  **Checked by:** a time-boxed (2h) spike — run floci-oci locally,
  point `oci_master_auth_and_endpoint()`'s `identity` endpoint at
  `http://localhost:4599`, exercise `oci_ensure_leaf_identity` once for
  each of the create-new and already-exists paths, and diff the actual
  response bodies against what today's mocks assume.
- **Claim:** GitHub-hosted runners (where `python-unit-tests` runs) pay
  no meaningful cold-start cost for a floci-oci container beyond what
  `compose-boot-test`/Molecule's DinD jobs already accept elsewhere in
  this pipeline.
  **Breaks if wrong:** the `python-unit-tests` job — currently fully
  offline per `docs/ci.md` ("every provider HTTP call and `rclone`
  invocation mocked") — picks up a real latency/flakiness cost for a
  narrow slice of coverage.
  **Checked by:** timing a `docker compose up floci-oci` + spike-test
  run against this repo's actual runner class, not assumed from
  floci-oci's own "fast enough for CI" claim.

## Consequences

- `python-unit-tests` stops being a pure-`MagicMock`, no-Docker suite
  for the classic-IAM slice specifically — a real behavior change to
  `docs/ci.md`'s current description, to update once this leaves
  draft.
- The SCIM/leaf surface — the part that actually runs on a schedule in
  production — gets no new coverage from this decision. Don't let
  adopting floci-oci for the smaller surface read as having addressed
  OCI test realism generally.
- If the spike shows floci-oci's Identity emulation doesn't match
  `oci_bootstrap.py`'s exact call shapes, the fallback is simply: don't
  adopt it, keep `MagicMock` everywhere, and revisit only on a
  floci-oci Identity Domains release.
