# LLDAP: Directory & LDAPS Cert Lifecycle

`lldap` is the directory backend for the whole homelab — Tinyauth binds to
it over LDAPS for every forward-auth check. Its LDAPS cert comes from the
internal `step-ca` (see [`step-ca.md`](step-ca.md)), issued and kept
current by two host-level Ansible roles rather than a sidecar container.

## One container, two host-level roles

| Component | Type | Purpose |
| :--- | :--- | :--- |
| `lldap` | Container | The directory itself. Serves LDAPS on `6360` and a web UI on `17170` (routed through Caddy, `auth: false` — it's the identity provider, so it can't sit behind its own auth check). |
| `step_ca_cert` | Role (`ansible/roles/step_ca_cert/`, `deploy.yaml`'s Play 6, called once for lldap and once for openbao — see [`openbao.md`](../secrets/openbao.md)) | For lldap's instance: issues the initial cert via `step ca certificate` (once, on a fresh `certs` volume) and installs a systemd `cert-renewer@lldap.timer` for every renewal after that. |
| `step_ca_client` | Role (`ansible/roles/step_ca_client/`) | Shared prerequisite: caches step-ca's root cert on the host at `/etc/step-ca/root_ca.crt`, bind-mounted (read-only) into whichever `step` invocation needs it. Also used by `tinyauth_ca_trust` (below). |

Renewal runs on the host: `step_ca_cert`'s systemd unit runs as `root` and
restarts the container via `docker compose`, with no Docker socket proxy. See
[ADR 0009 (Internal service certificates)](../../decisions/0009-internal-service-certificate-issuance-and-renewal/revision-000.md)
for why this replaced the old `certbot`/`dockerproxy` pair.

## Why renewal is a systemd timer, not an in-container daemon

Smallstep's own renewal docs recommend exactly this pattern — a
`cert-renewer@.service`/`.timer` template pair, not a long-running
`step ca renew --daemon` process — and `step_ca_cert`'s templates
(`ansible/roles/step_ca_cert/templates/`) are adapted from their real
`cert-renewer@.service`/`.timer` files
(github.com/smallstep/cli/tree/master/systemd), not hand-rolled from
scratch. The only real adaptation: their canonical `ExecStartPost`
reloads a systemd service unit matching the cert's name
(`systemctl try-reload-or-restart %i`) — there's no systemd unit
representing a Docker Compose service here, so it runs
`docker compose -f {{ compose_deploy_dir }}/%i/compose.yaml restart %i`
instead (or sends `SIGHUP` instead of restarting, for an instance whose
own env file sets `RENEW_ACTION=signal` — see
[`openbao.md`](../secrets/openbao.md)). That generalizes to any
`compose_deploy_dir/<app>/compose.yaml`-shaped step-ca consumer, not
just lldap — openbao's own instance already uses it (see
[`openbao.md`](../secrets/openbao.md)), and every app in this repo already follows
that layout (see [`adding-an-app.md`](../deploy/adding-an-app.md)).

A renewal failure shows up as a failed systemd unit
(`systemctl status cert-renewer@lldap.service`,
`journalctl -u cert-renewer@lldap.service`) and pages a Telegram topic
via `OnFailure=` (see
[`telegram-notifications.md`](../monitoring/telegram-notifications.md)).

## `step` runs via its container image, not a host-installed binary

Both `ExecCondition` and `ExecStart` in `cert-renewer@.service.j2` (and
`step_ca_cert`'s own one-time issuance task) run `step` as a throwaway
`smallstep/step-cli` container (`docker run --rm ...`) rather than a
package installed on the host. This repo has no other third-party apt
repo anywhere, and the container approach avoids being the first one:
`step_ca_client` only ever caches step-ca's root cert to a host path,
never installs anything.

The container mounts the app's own `<app>_certs` volume directly by
name — `%i_certs`, using systemd's own instance-parameter expansion —
rather than resolving that volume's host filesystem path first. Every
field that once needed a per-app copy of the whole template
(`CA_URL`/`STEP_CLI_IMAGE`/`NETWORK`, and — for openbao's own instance —
whether to restart or signal, and whether to chown the cert back to a
non-root user) is instead resolved via `%i`'s own
`/etc/cert-renewer/%i.env` (rendered per instance, read by systemd's
`EnvironmentFile=`), so the template itself stays one file, identical
for every instance. `--user root` on the container sidesteps a real,
confirmed issue: `smallstep/step-cli`'s default non-root user can read a
freshly created Docker volume's root directory but not write new files
into it.

## Why initial issuance and renewal use different auth

Initial issuance (`step_ca_cert`'s own Ansible task, once) authenticates
with the JWK provisioner password — there's no existing cert yet to
prove anything with. Renewal (the systemd timer, forever after)
authenticates via mTLS using the cert `step ca renew` is renewing —
`step ca renew`'s own documented default — so the provisioner password
is never written to disk outside that one-time Ansible run (rendered to
`/tmp`, used, removed in an `always:` block — see
`ansible/roles/step_ca_cert/tasks/main.yaml`).

## Cert SANs

The cert covers both `lldap` (the bare container name, for anything
reaching it over the `caddy-proxy` Docker network) and
`lldap.{{ caddy_domain }}` (the FQDN) in one `step ca certificate`
call — covers both ways a client might dial it, matching the reference
setup's own `--san` pattern.

## Closing tinyauth's trust gap

Once lldap's cert stops coming from a publicly-trusted CA, tinyauth's
own `insecure: false` (already the default — see `config.yaml.j2`) just
starts failing verification instead of silently doing nothing, unless
tinyauth is told to trust step-ca's root. tinyauth's schema has no
`caCert`/`caFile` option of its own (only `insecure` and the
unrelated `authCert`/`authKey` mTLS pair), so `tinyauth_ca_trust`
(`ansible/roles/tinyauth_ca_trust/`, same Play 6) takes a different
route: it concatenates the host's system CA bundle with step-ca's root
(from `step_ca_client`) and mounts the result into tinyauth's container
at `/data/ca-bundle.pem`, with `SSL_CERT_FILE` pointed at it
(`docker/tinyauth/compose.yaml`). Go's `crypto/x509.SystemCertPool()` on
non-macOS Unix honors that env var, extending the default trust store
rather than replacing it with something narrower.

`tinyauth_ca_trust`'s Molecule scenario
(`ansible/roles/tinyauth_ca_trust/molecule/default/`) deploys a real
tinyauth against a real step-ca-issued cert with
`tinyauth_ldap_insecure: false`, the production value. The run reaches
tinyauth's LDAP bind with no TLS error, so tinyauth's LDAP client does
honor `SSL_CERT_FILE`. If LDAPS verification against a step-ca-issued
cert fails in production, check for a tinyauth change that pins its own
`tls.Config` before suspecting this mechanism.

On a first-ever deploy, `SSL_CERT_FILE` points at a file that doesn't
exist until `tinyauth_ca_trust` runs (Play 6, after tinyauth's Play 4
deploy). tinyauth's LDAP bind runs at startup and exits on failure, so
it crash-loops briefly until Play 6 seeds the bundle and restarts it.
`restart: unless-stopped` absorbs this, as it does the observer-account
bootstrap race below. The scenario reproduces it and asserts on it
(`docker logs` shows at least two process starts; `RestartCount` is the
wrong signal, since a manual restart resets it).

## Bootstrapping the observer account

Tinyauth binds as a read-only `observer` account
(`uid=observer,ou=people,...`) to check logins — see
`docker/tinyauth/configs/config.yaml.j2`'s `ldap.bindDn`. The
`lldap_bootstrap` role (`ansible/roles/lldap_bootstrap`) creates and
maintains it: it runs lldap's own `bootstrap.sh` against a declarative
JSON config, adding the account to `lldap_strict_readonly` — a built-in
lldap group required for real login lookups (a bare bind would still
succeed without it, but every login check afterwards would silently
fail). `deploy.yaml`'s Play 7 runs it right after lldap's own deploy,
using the same `tinyauth-ldap-observer-password` secret `config.yaml.j2`
already renders — see
[`secrets.md`](../secrets/secrets.md#syncing-the-ldap-observer-account-password).

DO_CLEANUP=false, so it only ever touches the `observer` account. Safe
to re-run: `bootstrap.sh` updates the existing account in place instead
of erroring.

## Runtime config

`docker/lldap/configs/env.j2` sets `LLDAP_LDAP_BASE_DN` and
`LLDAP_LDAP_USER_PASS` (the initial admin password) from
`lab_domain`/`lldap_ldap_user_pass`, and `LLDAP_JWT_SECRET`/`LLDAP_KEY_SEED`
for its own token signing — all three generated once by the `secrets`
role. See [`secrets.md`](../secrets/secrets.md) for the generation mechanism and
[`volumes.md`](../deploy/volumes.md) for why `data`/`certs` are named volumes
rather than bind mounts.
