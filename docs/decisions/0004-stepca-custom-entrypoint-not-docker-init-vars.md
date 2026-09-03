# 0004. Custom step-ca entrypoint instead of `DOCKER_STEPCA_INIT_*`

**Status:** Accepted

## Context

The official `smallstep/step-ca` image ships its own non-interactive
bootstrap, driven by `DOCKER_STEPCA_INIT_*` environment variables, and
only initializes if `config/ca.json` doesn't exist yet. That
idempotency — and persisting the CA's identity in an external volume
rather than an image build layer — is why this repo uses the official
image at all, rather than baking `step ca init` into a Dockerfile at
build time the way the reference setup this was adapted from does (a
build-time `step ca init` regenerates a fresh random root key on every
image rebuild, silently rotating trust for every consumer already
bootstrapped against the old one).

The stock auto-init can't fully express this repo's design, though:

- It encrypts the CA's own keys and the initial JWK provisioner's key
  with the **same** password — there's no separate provisioner
  password.
- It has no flag for a provisioner's claim durations
  (`defaultTLSCertDuration`) — only `step ca provisioner update` (a
  separate, later command) can set that.

## Decision

Run the same underlying command (`step ca init`) by hand in a custom
`scripts/entrypoint.sh`, gated on the same `config/ca.json`-doesn't-exist
check the stock entrypoint uses, followed by one `step ca provisioner
update --x509-default-dur` call to set the claim duration explicitly.

## Consequences

`step-ca-password` and `step-ca-provisioner-password`
(`secrets_registry.yaml`) stay genuinely independent — matching
Smallstep's own production-considerations guide, which recommends
exactly this. A restart with an already-initialized `data` volume
skips straight to `exec step-ca`, same idempotency guarantee as the
stock entrypoint. The cost is one more script to maintain against
future `smallstep/step-ca` image changes, instead of relying entirely
on the vendored bootstrap.
