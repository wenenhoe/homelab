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
`docker/tinyauth/configs/config.yaml.j2`'s `ldap.bindDn`. Nothing in this
repo creates that account or sets its password; it's a one-time manual
step in lldap's own web UI (create the user, add it to a read-only
group, set its password to the value `secrets_registry.yaml` generated).
See [`secrets.md`](secrets.md#syncing-the-ldap-observer-account-password)
for the exact steps and how to read the generated password back out.

## Runtime config

`docker/lldap/configs/env.j2` sets `LLDAP_LDAP_BASE_DN` and
`LLDAP_LDAP_USER_PASS` (the initial admin password) from
`lab_domain`/`lldap_ldap_user_pass`, and `LLDAP_JWT_SECRET`/`LLDAP_KEY_SEED`
for its own token signing — all three generated once by the `secrets`
role. See [`secrets.md`](secrets.md) for the generation mechanism and
[`volumes.md`](volumes.md) for why `scripts` is a volume like `data`/`certs`
rather than a bind mount.
