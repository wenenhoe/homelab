# LLDAP: Directory & LDAPS Cert Lifecycle

`lldap` is the directory backend for the whole homelab — Tinyauth binds to
it over LDAPS for every forward-auth check. Its own compose stack is
three containers because `lldap` has no built-in ACME client and doesn't
hot-reload certs, so `certbot` owns the cert lifecycle for it.

## Three containers, one job

- **`lldap`** — the directory itself. Serves LDAPS on `6360` and a web
  UI on `17170` (routed through Caddy, `auth: false` — it's the identity
  provider, so it can't sit behind its own auth check).
- **`certbot`** — issues/renews the LDAPS cert via DNS-01
  (`certbot/dns-digitalocean`), looping `certbot renew` every 12h
  (`docker/lldap/scripts/entrypoint.sh`).
- **`dockerproxy`** — a `CONTAINERS=1`-scoped `docker-socket-proxy`,
  used only so `certbot` can restart `lldap` after a renewal without the
  real Docker socket ever being mounted into `certbot`.

## Why the cert has to be copied, not shared

`certbot` and `lldap` don't share a live cert volume — `certbot` writes
into its own Let's Encrypt state (`letsencrypt_conf`/`letsencrypt_lib`),
then its `--deploy-hook` (`docker/lldap/scripts/deploy-hook.sh`) copies
`fullchain.pem`/`privkey.pem` into the `certs` volume `lldap` actually
reads from (`LLDAP_LDAPS_OPTIONS__CERT_FILE`/`KEY_FILE` in
`docker/lldap/configs/env.j2`). Since `lldap` doesn't hot-reload TLS
certs on file change, the same deploy-hook then restarts it via
`restart-lldap.py`, which calls `dockerproxy`'s `/containers/lldap/restart`
over plain TCP — best-effort: a restart failure is logged and swallowed
rather than failing the renewal itself.

## Bootstrapping the observer account

Tinyauth binds as a read-only `observer` account
(`uid=observer,ou=people,...`) to check logins — see
`docker/tinyauth/configs/config.yaml.j2`'s `ldap.bindDn`. The
`lldap_bootstrap` role (`ansible/roles/lldap_bootstrap`) creates and
maintains it: it runs lldap's own `bootstrap.sh` against a declarative
JSON config, adding the account to `lldap_strict_readonly` — a built-in
lldap group required for real login lookups (a bare bind would still
succeed without it, but every login check afterwards would silently
fail). `deploy.yaml`'s Play 6 runs it right after lldap's own deploy,
using the same `tinyauth-ldap-observer-password` secret `config.yaml.j2`
already renders — see
[`secrets.md`](secrets.md#syncing-the-ldap-observer-account-password).

DO_CLEANUP=false, so it only ever touches the `observer` account. Safe
to re-run: `bootstrap.sh` updates the existing account in place instead
of erroring.

## Runtime config

`docker/lldap/configs/env.j2` sets `LLDAP_LDAP_BASE_DN` and
`LLDAP_LDAP_USER_PASS` (the initial admin password) from
`lab_domain`/`lldap_ldap_user_pass`, and `LLDAP_JWT_SECRET`/`LLDAP_KEY_SEED`
for its own token signing — all three generated once by the `secrets`
role. See [`secrets.md`](secrets.md) for the generation mechanism and
[`volumes.md`](volumes.md) for why `scripts` is a volume like `data`/`certs`
rather than a bind mount.
