# Beszel: Host & Container Monitoring

`beszel-hub` and `beszel-agent` are two entries in `app_catalog`. The hub runs once, on `security`; the agent runs on every
host in `app_hosts` (`security`, `services`, `play`, `storage`), including `security` itself. See [`docs/topics/deploy/adding-an-app.md`](../deploy/adding-an-app.md) for the general pattern this follows.

## Connection model

Hub and agent can talk over SSH (hub to agent) or WebSocket (agent to hub). This setup uses WebSocket, each agent connecting out to `beszel_hub_url`:

| Setting | Does |
| :--- | :--- |
| `TOKEN` | Identifies which system is connecting |
| `KEY` | The hub's public ED25519 key, so the agent can verify it reaches the real hub |
| `DISABLE_SSH=true` | The agent opens no listening port, although it runs on the host network |

So `services` and `play` need no inbound port open, and `iptables -P FORWARD DROP` hardening does not affect it as it can SSH mode. The handshake is in [Beszel's security docs](https://beszel.dev/guide/security).

## Why the hub skips Tinyauth

`beszel-hub`'s Caddy route sets `auth: false`, same reasoning as `lldap` and `cobalt`: the `/api/beszel/agent-connect` WebSocket handshake is machine-to-machine (TOKEN/KEY), not a browser session, and Tinyauth's `forward_auth` would block it before it ever reaches Beszel. The hub's own PocketBase login still gates the dashboard itself.

## Bootstrapping the KEY and TOKEN

`beszel_hub_key` and `beszel_agent_token` don't exist until *after* the
hub's first boot (the hub generates its keypair on first start; a token
is created by hand in its web UI). Both are `manual`-format
`secret_catalog.yaml` entries marked `allow_blank: true`, so a missing
value doesn't block the first deploy. `beszel-agent`'s `.env` uses
`no_log: true` like any other secret-bearing config (see
[`secrets.md`](../security/secrets.md)).

Sequence:

1. Deploy. The hub starts normally; the agents sit in a harmless auth-retry loop, since `openbao_utils/bootstrap.py` created both values empty.

   ```sh
   # from ansible/
   ansible-playbook playbooks/deploy.yaml
   ```

2. Visit `https://beszel.sec.{{ lan_domain }}` and create the hub admin account.
3. Copy the hub's public key from **Settings → Keys**, and a new universal token from **Settings → Tokens**. Store both, as `beszel-hub-key` and `beszel-agent-token`, when prompted (entries already set are skipped, so re-running is safe, see [`secrets.md`](../security/secrets.md)):

   ```sh
   cd tools && python3 -m openbao_utils.bootstrap
   ```

4. Deploy again with the command of step 1. Every agent's `.env` renders with the real values, and each host registers itself on its first successful handshake.

## Rotating the KEY and TOKEN

Both live in the hub's own PocketBase database, in its `data` volume, with the admin
account, every system's history and the notification config. So neither can be
replaced alone: rotating either means wiping the volume and bootstrapping again,
losing the history. Check the hub's `Settings → Keys` for a regenerate option first,
which would be a much smaller blast radius.

1. Wipe the hub back to an un-booted state, previewing first:

   ```sh
   # from ansible/: preview
   ansible-playbook playbooks/volume-reset.yaml --limit security,localhost \
     -e volume_reset_app=beszel-hub -e volume_reset_volume=data -e volume_reset_confirm=true --check
   ```

   ```sh
   # from ansible/: destructive
   ansible-playbook playbooks/volume-reset.yaml --limit security,localhost \
     -e volume_reset_app=beszel-hub -e volume_reset_volume=data -e volume_reset_confirm=true
   ```

2. Restart the hub empty. Every agent drops back into the auth-retry loop.

   ```sh
   # from ansible/
   ansible-playbook playbooks/deploy.yaml --limit security,localhost
   ```

3. Create the admin account again and copy a new KEY and TOKEN, as in steps 2 and 3
   of the bootstrap. Do not run `openbao_utils/bootstrap.py` here: it skips any
   entry already set, so it would change neither. Step 4 overwrites them.
4. Overwrite both Vault values directly — this is an update to an
   existing path, which `controller`'s AppRole can do (its policy grants
   `update` on `secret/data/hosts/*`, just not `delete` — see
   `controller.hcl`), so `openbao_utils/bootstrap.py`'s own skip-if-already-set
   behavior doesn't get in the way here:
   `value=-` reads from stdin instead of the command line, which a
   shell's own history file and process listing (`ps`) can both expose.
   `printf '%s'` adds no newline, where `<<<` would store one:

   ```sh
   # [1/4] controller: paste alone; it opens a shell and waits for the secret_id
   cd tools && python3 -m openbao_utils.shell "$(cat ../ansible/files/secrets/openbao-controller-role-id)"
   ```

   ```sh
   # [2/4] inside that shell: paste alone; it waits for the new KEY, hidden
   read -rs KEY; printf '%s' "$KEY" | bao kv put -mount=secret hosts/all/beszel/beszel-hub-key value=-; unset KEY
   ```

   ```sh
   # [3/4] same shell: paste alone; it waits for the new TOKEN, hidden
   read -rs TOKEN; printf '%s' "$TOKEN" | bao kv put -mount=secret hosts/all/beszel/beszel-agent-token value=-; unset TOKEN
   ```

   ```sh
   # [4/4] same shell
   exit
   ```
5. Deploy to every host in `app_hosts`, **not** `security` alone: each runs an agent that needs the new KEY.

   ```sh
   # from ansible/
   ansible-playbook playbooks/deploy.yaml --limit app_hosts,localhost
   ```

6. Confirm every host reappears as a connected system on the dashboard, then re-add the [notification channel](#alert-notifications) and the [alerts](#alerts), which were in the wiped database too.

## Rebuilding a host

An agent proves which machine it is to the hub with a fingerprint. The agent
keeps it in `/var/lib/beszel-agent/fingerprint`, in the `beszel-agent_data`
volume, and the hub saves it when the system first connects. A rebuilt host is
a new machine with a new volume, so its agent offers a fingerprint that
differs from the one saved for its predecessor. The hub accepts the WebSocket
and closes it at once, and the agent logs this on every retry:

```text
WARN Connection closed err="connection closed, code=1000, reason=fingerprint mismatch"
```

The token and key are fine, and the hub's other systems are unaffected. The
hub keeps one record per system in the `fingerprints` collection of its
database, and a reconnecting agent does not update it. To fix it:

1. Read the agent's fingerprint on the host:

   ```sh
   docker exec beszel-agent cat /var/lib/beszel-agent/fingerprint
   ```

2. Log in to the hub's database dashboard at `/_/` with the superuser account.
   The hub is built on PocketBase, and this is its own web tool for the
   database behind the hub.
3. Open the `fingerprints` collection, then the record whose `system` is the
   rebuilt host. Set its `fingerprint` field to the value from step 1 and save
   (**Unlock to save**, then **Save changes**).

Deleting the saved fingerprint on the hub's tokens page (`/settings/tokens`)
did not make the hub take the new one: the record stays, with an empty
`fingerprint`, and step 3 fills it. The hub has to be running for this, so after
a rebuild of `security` restore the hub first.

## Runtime config

| Compose file | Image | Network | Notes |
| :--- | :--- | :--- | :--- |
| `docker/beszel-hub/compose.yaml` | `henrygd/beszel` | Joins `caddy-proxy`, exposes `8090` to Caddy | Persists `data` volume to `/beszel_data` |
| `docker/beszel-agent/compose.yaml` | `henrygd/beszel-agent` | `network_mode: host` (required for host-level network interface stats — also means it doesn't join `caddy-proxy`, since it isn't routed through Caddy at all) | Container stats via a `dockerproxy` sidecar (`CONTAINERS=1`-scoped, socket mounted read-only), reached over `DOCKER_HOST: tcp://localhost:2375` rather than mounting the socket itself. The agent container and the sidecar both drop every capability and set `no-new-privileges` |

## Alerts

Not Ansible-managed: each system's alerts are set in the hub and live in its
database. `storage` has a disk usage alert, above 80% for 10 minutes, because
its disk holds the [on-site backup store](../records/seaweedfs.md#observability).
It is sent through the [notification channel](#alert-notifications).

## Alert notifications

Not Ansible-managed — Beszel's notification channels live in the hub's
own database, same "only exists after first boot" category as the
KEY/TOKEN above. Once logged in: **Settings → Notifications**, add
`telegram://<telegram_token>@telegram?chats=<telegram_chatid_monitoring>`
(both values from `ansible/inventory/group_vars/all/main.yaml`). See
[`telegram-notifications.md`](telegram-notifications.md) for the full
bot/topic scheme shared with backups and the cert checks.
