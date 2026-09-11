# Conventions

Naming and structural rules that hold across more than one component.
Not a decision record (no fork was weighed — these are patterns
already consistent across the repo) and not a topic doc (no single
component owns them). If a convention here ever needs a real trade-off
made about it, that becomes its own ADR and this doc links to it,
same as [`docs/README.md`](README.md) describes for any other topic.

## Naming case: Ansible-world vs Docker/systemd-world

Ansible identifiers — role names (`ansible/roles/*`), most playbook
filenames — are `snake_case`: `backup_agent`, `caddy_cert_expiry`,
`step_ca_cert`. Docker/systemd identifiers — `docker/<app>/` directory
names, compose service names, systemd unit filenames — are
`kebab-case`: `beszel-agent`, `step-ca`, `cloud-sync.timer`. Match the
world you're naming something for, not the file format it happens to
be written in (a `.yaml` playbook is Ansible-world; a `.service.j2`
template's *rendered filename* is systemd-world even though the
template itself lives under an Ansible role).

Known exception: `ansible/playbooks/ci_boot_test.yaml` is snake_case
and hasn't been renamed to match the rest of `playbooks/`.

## Vault KV paths

`secret/data/hosts/<hostname>/<concern>/<name>` mirrors
`host_vars/<hostname>.yaml`; `secret/data/hosts/all/<concern>/<name>`
mirrors `group_vars/all/*.yaml` — see
[ADR 0021](decisions/0021-vault-path-convention-hosts-all-for-global-secrets.md)
for why the split follows the inventory structure. Cloud provider
credentials are the one exception, on their own top-level
`secret/data/cloud_credentials/{leaf,rotation}/*` family instead of
under any host, since they anticipate a consumer split
(deploy-only vs. rotation-only identity) that `hosts/*` has no reason
to model — see [ADR 0021](decisions/0021-vault-path-convention-hosts-all-for-global-secrets.md)
and [ADR 0023](decisions/0023-openbao-repoint-not-native-plugin.md).

## systemd units

Named for the job they do, not the host or project running it — no
`homelab-` or hostname prefix (`cloud-sync.service`, not
`homelab-cloud-sync.service`). Templated straight to
`/etc/systemd/system/<name>.service` / `.timer` by the owning role
(e.g. `ansible/roles/cloud_sync/templates/cloud-sync.service.j2`), and
every task that writes one pairs it with a `notify: Reload systemd`
handler — a unit file changing without a reload is a real, non-obvious
way for a deploy to silently not take effect.

## Telegram topics

One Telegram topic per concern, shared across whichever apps alert
into it (`diun`, Beszel, backups, cert-renewal all route through the
same scheme) rather than one topic per app — see
[ADR 0011](decisions/0011-telegram-topics-not-direct-chat.md) and
[`telegram-notifications.md`](telegram-notifications.md) for the
concern → topic mapping itself.

## Not yet a convention

AppRole naming has only two real instances so far (`controller`,
`vault-bootstrap`) — not enough to generalize into a rule. Don't infer
a pattern from them; check the actual OpenBao docs for what exists
today.
