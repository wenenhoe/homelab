# step-ca: Service Record

The private certificate authority for internal TLS, on `security`. Its initialisation, certificate lifetime and client flow are in [`step-ca.md`](../services/step-ca.md). The catalog's facts (host, volumes, backup) are in the [coverage table](../disaster-recovery/coverage.md).

## Dependencies

- Needs the `caddy-proxy` network, the `data` and `scripts` volumes, and the `step-ca-password` and `step-ca-provisioner-password` secrets ([`step-ca.md`](../services/step-ca.md#secrets)). Those secrets are read from OpenBao at deploy time.
- Needs OpenBao for the deploy that renders its `.env`, and OpenBao needs it for its own certificate: the loop is broken by the `bootstrap-security.yaml` playbook ([`openbao-backup-restore.md`](../secrets/openbao-backup-restore.md#rebuilding-security)).
- Needed by `lldap` and `openbao` for their leaf certificates (`step_ca_cert`), and by `tinyauth` for the root it trusts to verify LDAPS (`tinyauth_ca_trust`).

## Data

- The CA's private keys, its password and its provisioner configuration, in the `data` volume.
- The root certificate is public. The two passwords are secrets.

## Exposure

- Reachable on `caddy-proxy` only, by container name on port 9000. It has no Caddy route and no published port ([`step-ca.md`](../services/step-ca.md#network)).
- Consumers authenticate with the provisioner password for first issuance and with their own certificate (mTLS) for renewal ([`lldap.md`](../services/lldap.md)).
- It makes no outbound calls that this record can name. Unknown: check the container's network traffic if that matters.
- It keeps one capability, `NET_BIND_SERVICE`, because the binary requires it ([`adding-an-app.md`](../deploy/adding-an-app.md#container-hardening)).

## Threat model

- Whoever holds the CA key or the provisioner password can mint a certificate any internal service would trust. Both passwords are generated and held in OpenBao, and the CA is reachable only from containers on `caddy-proxy`.
- A leaked leaf certificate lets its holder impersonate that one service until it expires; certificates last 720 hours ([ADR 0008](../../decisions/0008-internal-certificate-lifetime/revision-000.md)).
- Unknown: whether a host that joins `caddy-proxy` could reach port 9000 beyond the intended consumers. Check the network membership of every container on `security`.

## Observability

- The image's health check runs `step ca health` from inside the container, and Beszel reports the container's state ([`beszel.md`](../monitoring/beszel.md)).
- A CA that is up but not renewing shows as a missed `cert-renewer-*` or `cert-expiry-*` heartbeat in Gatus ([`gatus.md`](../monitoring/gatus.md)); Caddy's expiry alerting is in [`caddy.md`](../services/caddy.md#cert-expiry-alerting).

## Disaster recovery

Recovery tier 1. The `data` volume is backed up on the generic schedule ([`backup.md`](../disaster-recovery/backup.md)). A rebuild of `security` needs the CA archive fetched and decrypted by hand before any secret is reachable ([`rebuild-runbook.md`](../disaster-recovery/rebuild-runbook.md#still-done-by-hand)). Acceptable loss and downtime: Unknown; check [`exercises.md`](../disaster-recovery/exercises.md).

## Lifecycle

- Upgrade: bump the pinned image in the compose template and deploy. The initialisation runs only when `config/ca.json` is absent, so an upgrade does not reinitialise ([`step-ca.md`](../services/step-ca.md#custom-entrypoint-not-docker_stepca_init_)).
- Removal: Unknown. Removing the CA invalidates every certificate it issued; check the consumers listed above first.
- Waits on nothing at start. Everything else that uses TLS waits on it.
