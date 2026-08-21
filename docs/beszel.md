# Beszel: Host & Container Monitoring

`beszel-hub` and `beszel-agent` are two entries in `app_registry`. The hub runs once, on `security`; the agent runs on every
host in `app_hosts` (`security`, `services`, `play`, `storage`), including `security` itself. See [`docs/adding-an-app.md`](adding-an-app.md) for the general pattern this follows.

## Connection model

Hub and agent can talk over SSH (hub -> agent) or WebSocket (agent -> hub). This setup uses WebSocket: each agent makes an outbound connection to `beszel_hub_url`, authenticated by a `TOKEN` (identifies which system is connecting) and a `KEY` (the hub's public ED25519 key, so the agent can verify it's talking to the real hub). Nothing needs an inbound port opened on `services` or `play`, and it isn't affected by `iptables -P FORWARD DROP` hardening the way SSH mode can be — see [Beszel's security docs](https://beszel.dev/guide/security) for the full handshake.

## Why the hub skips Tinyauth

`beszel-hub`'s Caddy route sets `auth: false`, same reasoning as `lldap` and `cobalt`: the `/api/beszel/agent-connect` WebSocket handshake is machine-to-machine (TOKEN/KEY), not a browser session, and Tinyauth's `forward_auth` would block it before it ever reaches Beszel. The hub's own PocketBase login still gates the dashboard itself.

## Bootstrapping the KEY and TOKEN

`beszel_hub_key` and `beszel_agent_token` don't exist until *after* the
hub's first boot (the hub generates its keypair on first start; a token
is created by hand in its web UI). Both are `manual`-format
`secrets_registry.yaml` entries marked `allow_blank: true`, so a missing
value doesn't block the first deploy. `beszel-agent`'s `.env` uses
`no_log: true` like any other secret-bearing config (see
[`secrets.md`](secrets.md)).

Sequence:

1. `ansible-playbook deploy.yaml` — hub deploys and starts normally; agents deploy too, but sit in a harmless auth-retry loop (blank `KEY`/`TOKEN`, from the empty cache files `bootstrap_secrets.py` created for these two).
2. Visit `https://beszel.sec.{{ lab_domain }}`, create the hub admin account.
3. **Settings → Keys**: copy the hub's public key into `ansible/files/secrets/beszel-hub-key` (`printf '%s' '<key>' > ansible/files/secrets/beszel-hub-key`, or re-run `python3 ansible/bootstrap_secrets.py` and paste it in when prompted).
4. **Settings → Tokens**: create a universal token, copy it into `ansible/files/secrets/beszel-agent-token` the same way.
5. Re-run `ansible-playbook deploy.yaml` — every agent's `.env` re-renders with the real values and connects; each host self-registers as a system on first successful handshake.

## Rotating the KEY and TOKEN

Unlike a plain `secrets_registry.yaml` entry, there's no narrower way
to replace just the KEY or just the TOKEN — both live inside the hub's
own PocketBase database, in its `data` volume, alongside the admin
account, every system's historical monitoring data, and notification
config (`Settings → Notifications`, also DB-resident). Rotating either
one means wiping that whole volume and redoing the bootstrap sequence
above from scratch — there's no way to keep the history and only
replace the keypair. Check the hub's own `Settings → Keys` for a
regenerate option before doing this; if one exists there, it's a much
smaller blast radius than the below.

Sequence:

1. `ansible-playbook playbooks/volume-reset.yaml --limit security,localhost -e volume_reset_app=beszel-hub -e volume_reset_volume=data -e volume_reset_confirm=true` (`--check` first to preview) — wipes the hub back to a genuinely un-booted state.
2. `ansible-playbook playbooks/deploy.yaml --limit security,localhost` — hub restarts empty; every agent fleet-wide drops back into the same harmless auth-retry loop as first-time setup.
3. Redo bootstrap steps 2–4 above: new admin account, new KEY from `Settings → Keys`, new TOKEN from `Settings → Tokens`.
4. Overwrite both cache files: `ansible/files/secrets/beszel-hub-key` and `ansible/files/secrets/beszel-agent-token` (or `python3 ansible/bootstrap_secrets.py`, which only prompts for these two since everything else is already cached).
5. `ansible-playbook playbooks/deploy.yaml --limit app_hosts,localhost` — **not** `security` alone. Every host in `app_hosts` (`services`, `security`, `play`, `storage`) runs an agent that needs the new KEY to verify the hub again.
6. Confirm every host reappears as a connected system on the hub's dashboard, then re-add the Telegram notification channel from "Alert notifications" below — it lived in the wiped DB too and won't come back on its own.

## Runtime config

| Compose file | Image | Network | Notes |
| :--- | :--- | :--- | :--- |
| `docker/beszel-hub/compose.yaml` | `henrygd/beszel` | Joins `caddy-proxy`, exposes `8090` to Caddy | Persists `data` volume to `/beszel_data` |
| `docker/beszel-agent/compose.yaml` | `henrygd/beszel-agent` | `network_mode: host` (required for host-level network interface stats — also means it doesn't join `caddy-proxy`, since it isn't routed through Caddy at all) | Container stats via a `dockerproxy` sidecar (`CONTAINERS=1`-scoped, socket mounted read-only), reached over `DOCKER_HOST: tcp://localhost:2375` rather than mounting the socket itself |

## Alert notifications

Not Ansible-managed — Beszel's notification channels live in the hub's
own database, same "only exists after first boot" category as the
KEY/TOKEN above. Once logged in: **Settings → Notifications**, add
`telegram://<telegram_token>@telegram?chats=<telegram_chatid_monitoring>`
(both values from `ansible/inventory/group_vars/all/main.yaml`). See
[`telegram-notifications.md`](telegram-notifications.md) for the full
bot/topic scheme shared with diun and backups.
