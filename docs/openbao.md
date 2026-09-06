# OpenBao: Secrets Store Bootstrap

`openbao` is this migration's replacement for the file-based secrets
cache ([ADR 0001](decisions/0001-credential-caching-stage-1-before-secrets-manager.md)) —
see [`openbao-migration-roadmap.md`](openbao-migration-roadmap.md) for
the full build order. This doc covers Track A stage 1 only: deploying
it, its TLS cert, and getting it initialized and unsealed. Auth and
policies (stage 3) are covered in
[`openbao-auth.md`](openbao-auth.md); the secrets role migration
(stage 4) has its own doc once it lands. The actual backup/restore
drill (stage 2) has its own doc:
[`openbao-backup-restore.md`](openbao-backup-restore.md).

## Deployment

Single-node, integrated raft storage, on `security` — same trust tier
as `step-ca`/`tinyauth`/`lldap`
([0017](decisions/0017-openbao-bootstrap-secret-split.md)'s Context).
`docker/openbao/configs/openbao.hcl.j2` renders the raft/listener
config; `app_registry.yaml`'s `openbao` entry seeds it into a `config`
named volume the same way `dashy` seeds its `conf.yml`
([`volumes.md`](volumes.md)). `data` (raft state) and `certs` (TLS
material) are separate named volumes — `data` is the one volume in
this whole repo that must never be wiped by `cleanup.yaml`/a volume
reset outside a deliberate restore, since it's the only copy of
whatever's been written to Vault until stage 2's snapshot backup
exists and stage 6 retires the file cache it's currently backing up.

No `backup:` entry in `app_registry.yaml` — the generic `backup_agent`
path stops the container and tars its volumes
([`disaster-recovery.md`](disaster-recovery.md)), which for OpenBao
would mean sealing it (and a manual unseal per
[0021](decisions/0021-manual-shamir-unseal.md)) on every backup cycle.
OpenBao's own `bao operator raft snapshot save` is the backup mechanism
here instead — Track A stage 2, not yet built.

No `caddy:` entry either, same reasoning `step-ca` already documents:
an admin/secrets API isn't something to put behind an ordinary
reverse-proxy vhost. Unlike step-ca, though, OpenBao does need
reachability from other hosts eventually — `controller`-run plays on
hosts other than `security` will need to reach Vault's API once stage 4
lands. `compose.yaml.j2` publishes `8200` directly on the host
(`0.0.0.0:8200:8200`), the same bypass-Caddy-but-still-TLS approach
lldap's LDAPS listener uses (see [`lldap.md`](lldap.md)) — not proxied
HTTP-through-Caddy, since API/token clients don't want Caddy's
forward-auth in front of them the way a browser app does. The hostname
itself is a hand-written `extra_records` CNAME in
`host_vars/security.yaml` — bind9's auto-generated CNAMEs only fire for
apps with a `caddy:` route (see
[`reverse-proxy-and-dns.md`](architecture/reverse-proxy-and-dns.md)),
which this deliberately isn't, so it needed the same manual treatment
`sso` already gets in the same file.

`ui = false` in the rendered config — this repo's day-to-day OpenBao
consumers are Ansible and (once Track B lands) the CD agent, not a
human clicking through a browser. A human who needs to look inside
Vault directly can still do it from the CLI (`docker exec -it openbao
bao ...`, see below) or `ssh -L 8200:localhost:8200` for a one-off UI
session; there's no standing need to expose it.

## TLS

`openbao_cert` (`ansible/roles/openbao_cert/`, `deploy.yaml`'s Play 6)
issues OpenBao's leaf cert from step-ca and installs a
`cert-renewer@openbao.timer`, the same one-time-issuance-then-renewal
shape [`lldap_cert`](lldap.md) uses for lldap's LDAPS cert — same
provisioner-password-for-initial-issuance/mTLS-for-renewal split, same
`smallstep/step-cli` image rather than a host-installed `step` binary.
The two roles' generic `cert-renewer@.service`/`.timer` templates both
install to the same literal path (`/etc/systemd/system/cert-renewer@.service`,
shared by every `%i` instance — there's only ever one file on disk, and
whichever role runs last in Play 6 wins), and are near-identical, but
not byte-identical: `openbao_cert`'s copy has one addition, guarded on
`%i` so it's a no-op for `cert-renewer@lldap.timer` — see the section
below for why openbao needs it and lldap doesn't.

On a genuinely first deploy, the `certs` volume starts empty and
`openbao.hcl`'s listener requires `tls_cert_file`/`tls_key_file` to
exist — the container is expected to fail to start and be retried by
`restart: unless-stopped` until Play 6 issues the cert and restarts it.
This is the same bootstrap race [`lldap.md`](lldap.md) documents for
tinyauth's first-ever deploy; OpenBao's own exact failure mode on a
missing cert file hasn't been independently confirmed (Vault/OpenBao's
listener startup behavior here wasn't checked against upstream source
before writing this), but the fallback either way is the same tolerated
crash-loop, so nothing about first-deploy behavior depends on knowing
the exact failure message.

## Non-root user, and what it costs

`openbao/openbao`'s own Dockerfile (checked directly, not inferred)
creates a system user named `openbao`, `chown -R openbao:openbao
/openbao` at build time, then `USER openbao` — the container process
never runs as root. lldap has the same property but manages it itself
(`LLDAP_UID`/`LLDAP_GID` env vars its own entrypoint reads); OpenBao's
image has no such mechanism, so this repo has to handle two
consequences directly:

- A freshly-created named volume is root-owned, and the `openbao` user
  can't write into one it doesn't own. Fixed for the raft data volume
  by [`roles/openbao`](../ansible/roles/openbao) — a plain, guarded
  `docker run --rm --user root ... chown -R openbao:openbao` that only
  actually runs when the volume's current owner doesn't already match,
  checked before every deploy. By username, not a hardcoded UID:
  `adduser -S` assigns that number at image-build time, and it's not
  this repo's business to pin it.

  A one-shot `openbao-init` compose service (`depends_on:
  condition: service_completed_successfully`) doesn't work for this:
  Compose brings every service to "running" on `docker compose up`, and
  a `restart: "no"` container that already exited successfully doesn't
  count as running — so Compose restarts it on *every* `up`, which
  `community.docker.docker_compose_v2` reports as changed,
  unconditionally, forever. `openbao` is self-managed
  (`compose_self_managed_apps`, same mechanism `caddy`/`bind9` use, see
  [`deployment-flow.md`](deployment-flow.md)'s Play 4) specifically so
  this chown could be a plain guarded task instead.
- `step ca certificate`/`step ca renew` both run as `--user root` too
  (same freshly-created-volume issue `lldap_cert` already documents),
  so every issuance and every renewal leaves `fullchain.pem`/`privkey.pem`
  root-owned — which the non-root `openbao` process then can't read.
  `openbao_cert`'s issuance task, and a second, `%i`-guarded
  `ExecStart=` line in the shared `cert-renewer@.service` template,
  both chown the `certs` volume back to `openbao:openbao` by the same
  by-username approach right after `step` runs. This one was a plain
  Ansible task and a systemd `ExecStart=` line from the start, never a
  compose service, so it never hit the same problem.

## Duplicate configuration warning

Don't pass `command: ["server", "-config=/openbao/config/openbao.hcl"]`
in `compose.yaml.j2` — the image's own entrypoint already scans
`/openbao/config` as a directory by default
([Docker Hub](https://hub.docker.com/r/openbao/openbao): "the server
will load any HCL or JSON configuration files placed here by binding a
volume"), so an explicit `-config=` flag loads the same file a second
time, producing `WARNING: ignoring duplicate configuration found in
directory: /openbao/config/openbao.hcl`. `command: ["server"]` alone is
correct and relies on that default scan.

## Healthcheck

`compose.yaml.j2` runs `bao status -address=https://127.0.0.1:8200`
with `BAO_SKIP_VERIFY: true` (confirmed against
[openbao.org's environment-variable reference](https://openbao.org/docs/commands/#bao_skip_verify) —
loopback-only, against our own internal CA's cert, so there's no real
trust decision being loosened here, unlike using it against a real
remote OpenBao). Worth knowing before treating "unhealthy" here the
same as any other app in this repo: `bao status` exits non-zero
whenever OpenBao is *sealed or uninitialized*, not just when it's
genuinely down (confirmed against openbao.org's own CLI exit-code
docs for the sealed case: it's a "remote error", exit 2; the
uninitialized case isn't separately documented there, but it's the
same category of "server up, not yet able to serve" response, and
`bao status`'s own output distinguishes `Initialized: false` the same
way it reports `Sealed: true` — treating both as the same class of
"unhealthy" here, not confirmed byte-for-byte against a live exit
code). Since
[0021](decisions/0021-manual-shamir-unseal.md) means every restart
leaves OpenBao sealed until a human runs the unseal command above
(and a genuinely fresh deploy starts out uninitialized on top of
that), this container will show unhealthy in Beszel/Uptime-Kuma for
both stretches — an accurate reflection of "not currently serving
anything", not a false alarm, but a different meaning than "unhealthy"
carries for every other app here.

## Cert renewal uses SIGHUP, not a restart

`cert-renewer@openbao`'s `ExecStartPost` sends `SIGHUP`, not a restart
— guarded on `%i` in the shared template so lldap's own renewal is
unaffected (a restart is free for lldap, which has no seal state to
lose). Restarting OpenBao on every renewal would reseal the vault at
whatever cadence cert renewal fires, not just on reboot — undermining
[0021](decisions/0021-manual-shamir-unseal.md)'s cost-benefit premise
that unseal only costs a human at the moments they're already at the
keyboard.

Three things back the SIGHUP approach:

- OpenBao's TCP listener documents `tls_cert_file`/`tls_key_file` as
  "reloads-on-SIGHUP"
  ([openbao.org](https://openbao.org/docs/configuration/listener/tcp/)).
- HashiCorp's own Vault SIGHUP reference (OpenBao's upstream, same
  listener code lineage) is explicit that a SIGHUP reloads listener
  TLS certs and leaves everything else — seal state included —
  untouched: ["TLS certificates used by Vault listeners are
  reloaded"](https://support.hashicorp.com/hc/en-us/articles/5767318985107-Vault-SIGHUP-Behavior),
  with no mention of seal state anywhere in that document.
- `dumb-init` (this image's entrypoint) forwards received signals to
  its child by default — confirmed against its own README, not
  inferred from general container-init behavior.

One real caveat: OpenBao issue
[#2915](https://github.com/openbao/openbao/issues/2915) reports a
SIGHUP-triggered seal-client wedge on 2.5.2, but only for the
combination of `seal "gcpckms"` plus a declarative `audit "file"`
config stanza, neither of which this deployment uses (Shamir seal, no
audit device configured). Worth re-checking if either changes later.

`openbao_cert/molecule/default`'s own scenario runs the exact
`ExecStartPost` command, confirms `StartedAt` doesn't change (proving
it didn't restart), and confirms — via a raw `openssl s_client` TLS
handshake, not `bao status` — that the listener is actually serving the
renewed cert's serial afterwards, not just that the file on disk
changed (100.0%, 14/14 tasks, in
`ansible/molecule-coverage/thresholds.yaml`). A real forced renewal on
`security` itself has since confirmed the same thing outside Molecule:
`bao status` before and after showed an identical `Active Since`
timestamp and unchanged raft indices, and `docker ps` showed the
container's uptime never reset — `dumb-init` forwarding the signal
through to `bao`, and `bao` reloading without resealing, are no longer
documentation-only claims.

## Init and unseal — manual, not scripted

[0021](decisions/0021-manual-shamir-unseal.md) chose manual Shamir
unseal over cloud auto-unseal specifically because a human is already
at the keyboard for every reboot `security` has ever had. That's also
the reason this is written up as a runbook below rather than as a
Python wrapper script:

- `bao operator init`'s *output* — the unseal key shares and initial
  root token — is the sensitive part, and it only exists at the moment
  the command runs. No amount of `getpass`-style input-hiding helps
  here; the risk is capturing and storing that output correctly, which
  a script would still leave entirely to the operator (or would have to
  write to a file to avoid leaving to the operator — the opposite of
  what this needs).
- `bao operator unseal`'s prompt for each key share is already
  masked-input by the `bao` CLI itself. A wrapper adds a second place
  key material could end up in a stack trace or a log line, for no
  capability the CLI doesn't already have.
- Running either through Ansible (rather than an operator's own
  interactive shell) means the output flows through Ansible's own
  result-capture/`--diff` machinery — exactly what `no_log: true`
  exists to prevent elsewhere in this repo, and init/unseal output
  can't be `no_log`-suppressed and also be legible to the human who
  needs to transcribe it.

So: SSH to `security` directly and run these by hand, never via
`ansible-playbook`.

### First init (once, ever, per raft dataset)

```sh
docker exec -it openbao bao operator init -key-shares=3 -key-threshold=2
```

3 shares / 2 threshold, not the CLI's own 5/3 default: this is a
solo-operator homelab, so more shares than storage locations doesn't
add security, just more copies of the same material to account for.
Threshold 2-of-3 means losing any *one* stored copy doesn't lock you
out, while no single copy unseals it alone.

The command prints 3 unseal key shares and an initial root token,
**once** — nothing re-displays them later. Before doing anything else:

1. Copy all 3 unseal key shares and the root token into the password
   manager entry this repo already uses for the backup GPG key and (once
   generated) the snapshot read-only credentials
   ([`create_snapshot_readonly_keys.py`](../ansible/cloud_credentials/create_snapshot_readonly_keys.py)) —
   same offline handling, one entry.
2. Print or write down one of the three shares and store it physically
   offline, separate from the password manager — the same
   two-copies-not-one pattern [`disaster-recovery.md`](disaster-recovery.md)
   uses for the GPG private key.
3. Do not leave any of this in shell scrollback, a file on `security`,
   or a file on `controller`. Nothing here is written to
   `ansible/files/secrets/` — that cache is exactly the mechanism this
   migration retires.

The root token is not one of 0017's two recovery-critical items, but
treat it with the same discipline for now: it's the only credential
that can configure anything in a freshly-initialized, empty Vault.
[`openbao-auth.md`](openbao-auth.md) (Track A stage 3) is what gives
`controller` its own AppRole and revokes this initial root token once
that AppRole is proven — don't revoke it before then, and don't leave
it standing indefinitely after.

### Unsealing (every restart of the `openbao` container)

```sh
docker exec -it openbao bao operator unseal
```

Run it 2 times (the threshold above), each time pasting one of the 3
shares when prompted. `bao status` (same `docker exec` prefix) shows
current seal state without needing a share.

## Secrets

Nothing in `secrets_registry.yaml` backs OpenBao's own credentials —
by design, this is the thing everything else in that registry will
eventually move into. The one registry entry this stage adds,
`uptime-kuma-push-url-cert-renewer-openbao`, is unrelated: it's the
push-monitor URL for the cert-renewal timer, same shape as
[`lldap.md`](lldap.md)'s identical entry for lldap.

## Open follow-up

`cert-renewer@openbao.timer` hasn't yet fired entirely on its own
schedule, unattended — every renewal so far has been forced by hand.
Every piece it's built from (`ExecCondition`'s gate, the
renew/chown/reload sequence itself) has been exercised for real; this
is closing the loop on the last untested piece, not proving anything
new.

[`openbao-migration-roadmap.md`](openbao-migration-roadmap.md)'s stage
1 row is `Done`.
