# OpenBao: Secrets Store Bootstrap

`openbao` is this migration's replacement for the file-based secrets
cache ([ADR 0001](decisions/0001-credential-caching-stage-1-before-secrets-manager.md)) —
see [`openbao-migration-roadmap.md`](openbao-migration-roadmap.md) for
the full build order. This doc covers Track A stage 1 only: deploying
it, its TLS cert, and getting it initialized and unsealed. Auth
policies (stage 3), the secrets role migration (stage 4), and the
actual backup/restore drill (stage 2) are separate stages with their
own docs once they land.

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
forward-auth in front of them the way a browser app does.

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

  The first version of this fix put the chown in a one-shot
  `openbao-init` *compose service* instead, gated with `depends_on:
  condition: service_completed_successfully`. Confirmed live, via
  `./molecule-test-all.sh openbao_cert`'s idempotence check: `docker
  compose up` brings every service to "running", and a `restart: "no"`
  container that already exited successfully doesn't count as running
  — so Compose restarts it on *every* `up`, which
  `community.docker.docker_compose_v2` reports as changed,
  unconditionally, forever. `openbao` is self-managed now
  (`compose_self_managed_apps`, same mechanism `caddy`/`bind9` already
  use, see [`deployment-flow.md`](deployment-flow.md)'s Play 4)
  specifically so this chown could be a plain guarded task instead of
  a service Compose has any opinion about.
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

Neither of these showed up in review — the certs-volume fix came from
an actual first deploy attempt crash-looping with `permission denied`
on `/openbao/data/vault.db`; the data-volume fix's *first* version
(the `openbao-init` service) came from fixing that, and its own bug
came from an actual `./molecule-test-all.sh` run once Molecule coverage
existed to catch it — which is the reason to actually run things on
real hardware and in CI before trusting any of it (see "Open follow-up"
below).

## Duplicate configuration warning

An earlier version of `compose.yaml.j2` passed `command: ["server",
"-config=/openbao/config/openbao.hcl"]`. Confirmed live: this produced
`WARNING: ignoring duplicate configuration found in directory:
/openbao/config/openbao.hcl` — the image's own entrypoint already
scans `/openbao/config` as a directory by default (documented on
[Docker Hub](https://hub.docker.com/r/openbao/openbao): "the server
will load any HCL or JSON configuration files placed here by binding a
volume"), so the explicit flag loaded the same file a second time.
Fixed by dropping the flag entirely — `command: ["server"]`, relying
on the default directory scan, which is exactly what mounting
`openbao.hcl` at `/openbao/config/openbao.hcl` is already set up for.

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

## Open question: cert renewal currently reseals OpenBao

Not yet resolved, flagging rather than deciding: `cert-renewer@openbao`'s
`ExecStartPost` restarts the `openbao` container after every renewal —
the same mechanism `lldap_cert` uses, copied over without checking
whether it still made sense for this app. For lldap that's free (no
seal state to lose); for OpenBao it means every renewal reseals the
vault, requiring a manual unseal at whatever cadence cert renewal
actually fires — not just "every reboot of `security`", which is the
premise [0021](decisions/0021-manual-shamir-unseal.md)'s
cost-benefit reasoning was actually built on.

OpenBao's TLS listener documents `tls_cert_file`/`tls_key_file` as
"reloads-on-SIGHUP" ([openbao.org](https://openbao.org/docs/configuration/listener/tcp/)),
which would let `cert-renewer@openbao` pick up a renewed cert without
resealing at all — but whether that actually works end-to-end through
this image's `dumb-init` entrypoint hasn't been confirmed live, and
this doc isn't the place to guess given how much guessing has already
needed correcting during this stage's first real deploy. Needs an
actual test (`docker kill -s HUP openbao`, then confirm both that the
process is still up *and* serving the renewed cert) before either
keeping the restart or switching to it.

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
Track A stage 3 (auth/policies) is what gives `controller` its own
AppRole; once that's live and proven, revoke this initial root token
(`bao token revoke -self`, run with it still active) rather than
leaving a standing root credential around indefinitely.

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

## Open follow-up before this stage counts as proven

- No Molecule coverage for `openbao_cert` yet — see
  [`molecule-testing.md`](molecule-testing.md)'s row for it. Needs a
  `default` scenario mirroring `lldap_cert`'s (real step-ca, real
  issuance, real renewal-unit side effects) and a `not_running` guard
  scenario.
- The cert-renewal-reseals-OpenBao question above — restart vs.
  SIGHUP-reload — needs an actual test, not a decision made here.
- The data-volume and certs-volume permission fixes, and the
  duplicate-config fix, are all confirmed against one real deploy
  attempt's actual failure, but the *fixed* compose file and
  `openbao_cert` role haven't yet been run end-to-end themselves — a
  clean redeploy through init and unseal still needs to happen before
  treating this as settled.
- Everything above still needs to happen before
  [`openbao-migration-roadmap.md`](openbao-migration-roadmap.md)'s
  stage 1 row moves from `In progress` to `Done`.
