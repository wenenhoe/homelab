# LLDAP: Directory & LDAPS Cert Lifecycle

`lldap` is the directory backend for the whole homelab — Tinyauth binds to
it over LDAPS for every forward-auth check. Its LDAPS cert comes from the
internal `step-ca` (see [`step-ca.md`](step-ca.md)), issued and kept
current by two host-level Ansible roles rather than a sidecar container.

## One container, two host-level roles

- **`lldap`** — the directory itself. Serves LDAPS on `6360` and a web
  UI on `17170` (routed through Caddy, `auth: false` — it's the identity
  provider, so it can't sit behind its own auth check).
- **`lldap_cert`** (`ansible/roles/lldap_cert/`, `deploy.yaml`'s Play 6)
  — issues the initial cert via `step ca certificate` (once, on a fresh
  `certs` volume) and installs a systemd `cert-renewer@lldap.timer` for
  every renewal after that.
- **`step_ca_client`** (`ansible/roles/step_ca_client/`) — shared
  prerequisite: caches step-ca's root cert on the host at
  `/etc/step-ca/root_ca.crt`, bind-mounted (read-only) into whichever
  `step` invocation needs it. Also used by `tinyauth_ca_trust` (below).

This replaces the previous `certbot`/`dockerproxy` sidecar pair
entirely — `certbot`'s only job was DNS-01 issuance against
DigitalOcean, and `dockerproxy` existed solely to give `certbot` a
locked-down path to restart `lldap` after a renewal without mounting the
real Docker socket into it. Neither problem exists once renewal moves to
the host: `lldap_cert`'s systemd unit runs as `root` directly and
restarts the container via `docker compose`, no proxy needed.

## Why renewal is a systemd timer, not an in-container daemon

Smallstep's own renewal docs recommend exactly this pattern — a
`cert-renewer@.service`/`.timer` template pair, not a long-running
`step ca renew --daemon` process — and `lldap_cert`'s templates
(`ansible/roles/lldap_cert/templates/`) are adapted from their real
`cert-renewer@.service`/`.timer` files
(github.com/smallstep/cli/tree/master/systemd), not hand-rolled from
scratch. The only real adaptation: their canonical `ExecStartPost`
reloads a systemd service unit matching the cert's name
(`systemctl try-reload-or-restart %i`) — there's no systemd unit
representing a Docker Compose service here, so it runs
`docker compose -f {{ compose_deploy_dir }}/%i/compose.yaml restart %i`
instead. That happens to generalize to any future
`compose_deploy_dir/<app>/compose.yaml`-shaped step-ca consumer, not
just lldap, since every app in this repo already follows that layout
(see [`adding-an-app.md`](adding-an-app.md)).

This directly replaces the shell loop the old `certbot` entrypoint ran
(`while :; do certbot renew ...; sleep 12h; done`) — the compose file's
own `NOTE: Need more investigation` comment on that service already
flagged it as under-trusted — with `step`'s own renewal logic and a
timer systemd itself supervises: a renewal failure now shows up as a
failed systemd unit (`systemctl status cert-renewer@lldap.service`,
`journalctl -u cert-renewer@lldap.service`), not a silently-swallowed
exception inside a best-effort deploy hook.

## `step` runs via its container image, not a host-installed binary

Both `ExecCondition` and `ExecStart` in `cert-renewer@.service.j2` (and
`lldap_cert`'s own one-time issuance task) run `step` as a throwaway
`smallstep/step-cli` container (`docker run --rm ...`) rather than a
package installed on the host. This repo has no other third-party apt
repo anywhere, and the container approach avoids being the first one:
`step_ca_client` only ever caches step-ca's root cert to a host path,
never installs anything.

The container mounts the app's own `<app>_certs` volume directly by
name — `%i_certs`, using systemd's own instance-parameter expansion —
rather than resolving that volume's host filesystem path first. That
also means the generic template needs no per-instance override at all:
every field that used to require one (`CERT_LOCATION`/`KEY_LOCATION`)
is now derived entirely from `%i`, so any future step-ca consumer
following the same `ensure_volume.yaml` volume-naming convention (see
[`volumes.md`](volumes.md)) gets a working renewer with zero extra
wiring. `--user root` on the container sidesteps a real, confirmed
issue: `smallstep/step-cli`'s default non-root user can read a freshly
created Docker volume's root directory but not write new files into it.

## Why initial issuance and renewal use different auth

Initial issuance (`lldap_cert`'s own Ansible task, once) authenticates
with the JWK provisioner password — there's no existing cert yet to
prove anything with. Renewal (the systemd timer, forever after)
authenticates via mTLS using the cert `step ca renew` is renewing —
`step ca renew`'s own documented default — so the provisioner password
is never written to disk outside that one-time Ansible run (rendered to
`/tmp`, used, removed in an `always:` block — see
`ansible/roles/lldap_cert/tasks/main.yaml`).

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
`caCert`/`caFile` option of its own (confirmed — only `insecure` and the
unrelated `authCert`/`authKey` mTLS pair), so `tinyauth_ca_trust`
(`ansible/roles/tinyauth_ca_trust/`, same Play 6) takes a different
route: it concatenates the host's system CA bundle with step-ca's root
(from `step_ca_client`) and mounts the result into tinyauth's container
at `/data/ca-bundle.pem`, with `SSL_CERT_FILE` pointed at it
(`docker/tinyauth/compose.yaml`). Go's `crypto/x509.SystemCertPool()` on
non-macOS Unix honors that env var, extending the default trust store
rather than replacing it with something narrower.

**Confirmed via a live run**: `tinyauth_ca_trust`'s own Molecule scenario
(`ansible/roles/tinyauth_ca_trust/molecule/default/`) deploys a real
tinyauth pointed at a real step-ca-issued cert with
`tinyauth_ldap_insecure: false` — the real production value, unlike
`tinyauth/molecule/default`'s own scenario, which sets it `true` because
its lldap target has no step-ca behind it at all. A real run of this
scenario reached tinyauth's LDAP bind attempt with no TLS/certificate
error at all — the only failure was `LDAP Result Code 49 "Invalid
Credentials"`, an authentication-layer error that can only happen after
the TLS handshake itself already succeeded. That's a genuine,
live-observed confirmation that tinyauth's LDAP client does defer to
Go's default system cert pool via `SSL_CERT_FILE`, not just a design
intention that's never been run. (The `Invalid Credentials` itself
traced to a real, separate gap in this scenario — it never ran
`lldap_bootstrap` against its lldap target, so no `observer` account
existed to bind as — now fixed, mirroring `tinyauth/molecule/default`'s
own identical step.) If LDAPS verification against a step-ca-issued cert
ever fails in production despite this, something else changed (a
tinyauth version bump pinning its own `tls.Config`, most likely) — check
there first, not the mechanism this run already confirmed works.

On a genuinely first-ever deploy, tinyauth's `SSL_CERT_FILE` points at a
file that doesn't exist yet until `tinyauth_ca_trust` runs (Play 6,
after tinyauth's own Play 4 deploy) — Go's documented behavior for a
missing `SSL_CERT_FILE` is to silently contribute no roots from it
rather than crash the process outright, but since tinyauth's own LDAP
bind still runs at startup and exits on failure, it will crash-loop
briefly regardless until Play 6 seeds the real bundle and restarts it.
`restart: unless-stopped` absorbs this the same way it already absorbs
the observer-account bootstrap race below — not a new failure mode this
PR introduces, the same shape as one this repo already tolerates, and
exactly what `tinyauth_ca_trust`'s own scenario deliberately reproduces
and asserts on (its own `docker logs` shows at least two real process
starts — `RestartCount` itself turned out to be the wrong signal here,
since a manual restart resets it rather than just leaving it
unincremented) rather than routing around.

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
[`volumes.md`](volumes.md) for why `data`/`certs` are named volumes
rather than bind mounts.
