# Tinyauth: Service Record

The forward-auth gate in front of every Caddy route that does not set `auth: false`, on `security`. Its trust of the internal CA is in [`lldap.md`](../services/lldap.md#closing-tinyauths-trust-gap); the catalog's facts are in the [coverage table](../disaster-recovery/coverage.md).

## Dependencies

- Needs `lldap` for logins (LDAPS, bound as the read-only `observer` account), `step-ca`'s root in its trust file (`tinyauth_ca_trust` writes `ca-bundle.pem` into its volume), and the `caddy-proxy` network.
- Its rendered `config.yaml` holds the observer password, which comes from OpenBao.
- Needed by Caddy: every route without `auth: false` calls it before proxying ([`caddy.md`](../services/caddy.md)). If it is down, those apps answer with the auth failure.

## Data

- A SQLite database in the `data` volume: sessions and login state. Account data is not here; it stays in lldap.
- `config.yaml` is mode `0600` and holds the observer bind password, a secret.

## Exposure

- Reachable on `caddy-proxy` as `tinyauth:3000` and through its own host name for the login page. It is the auth service, so it carries no forward auth of its own.
- It calls lldap over LDAPS, verifying the certificate against the step-ca root.
- Sessions use secure cookies and last a day; the config sets three login retries and a 300-second login timeout (`config.yaml.j2`).
- It keeps `DAC_OVERRIDE` and drops everything else ([`adding-an-app.md`](../deploy/adding-an-app.md#container-hardening)).

## Threat model

- A flaw or misconfiguration in the gate exposes every app behind it. The config denies nothing by default at the ACL level (`policy: allow`); access control is that the login must succeed. Unknown: whether any app needs a per-group restriction; check the `acls` section against the apps' sensitivity.
- A stolen session cookie gives access until it expires.
- A bypass through a route with `auth: false` is a catalog decision, shown in the [coverage table](../disaster-recovery/coverage.md).
- Analytics are off in its config.

## Observability

- Container health and state are in Beszel ([`beszel.md`](../monitoring/beszel.md)); the archive is covered by the backup heartbeats in Gatus ([`gatus.md`](../monitoring/gatus.md)).
- Unknown: whether a login-failure spike is noticed. Its audit log stream is disabled in the config; check before relying on it.

## Disaster recovery

Backed up: `data`, with the container stopped during the archive so SQLite is not copied mid-write ([`backup.md`](../disaster-recovery/backup.md)). It is restored together with `lldap`. Losing it loses the sessions, not the accounts. Acceptable loss and downtime: Unknown; check [`exercises.md`](../disaster-recovery/exercises.md).

## Lifecycle

- Upgrade: bump the pinned image in the compose file and deploy; the image tag follows the `v5` major.
- Removal: removing it leaves every gated route unable to authorise requests.
- Waits on `lldap` and `tinyauth_ca_trust`. On a first boot before the trust file exists, it restarts until it does.
