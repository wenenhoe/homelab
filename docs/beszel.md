# Beszel: Host & Container Monitoring

`beszel-hub` and `beszel-agent` are two entries in `app_registry`. The hub runs once, on `security`; the agent runs on every
host in `app_hosts` (`security`, `services`, `play`), including `security` itself. See [`docs/adding-an-app.md`](adding-an-app.md) for the general pattern this follows.

## Connection model

Hub and agent can talk over SSH (hub -> agent) or WebSocket (agent -> hub). This setup uses WebSocket: each agent makes an outbound connection to `beszel_hub_url`, authenticated by a `TOKEN` (identifies which system is connecting) and a `KEY` (the hub's public ED25519 key, so the agent can verify it's talking to the real hub). Nothing needs an inbound port opened on `services` or `play`, and it isn't affected by `iptables -P FORWARD DROP` hardening the way SSH mode can be — see [Beszel's security docs](https://beszel.dev/guide/security) for the full handshake.

## Why the hub skips Tinyauth

`beszel-hub`'s Caddy route sets `auth: false`, same reasoning as `lldap` and `cobalt`: the `/api/beszel/agent-connect` WebSocket handshake is machine-to-machine (TOKEN/KEY), not a browser session, and Tinyauth's `forward_auth` would block it before it ever reaches Beszel. The hub's own PocketBase login still gates the dashboard itself.

## Bootstrapping the KEY and TOKEN

Unlike the rest of `app_registry`'s `.env` secrets (which are supplied up front via `deploy.yaml`'s `vars_prompt` and protected with `force: false` so a re-run never clobbers them), `beszel_hub_key` and `beszel_agent_token` don't exist until *after* the hub's first boot — the hub generates its own keypair on first start, and a token is created by hand in its web UI. So `beszel-agent`'s `.env` config uses `force: true` deliberately: it must re-render once these values are known.

Sequence:

1. `ansible-playbook deploy.yaml` — hub deploys and starts normally; agents deploy too, but sit in a harmless auth-retry loop (blank `KEY`/`TOKEN`).
2. Visit `https://beszel.sec.{{ lab_domain }}`, create the hub admin account.
3. **Settings → Keys**: copy the hub's public key into `beszel_hub_key` in `group_vars/all.yaml`.
4. **Settings → Tokens**: create a universal token, copy it into `beszel_agent_token`.
5. Re-run `ansible-playbook deploy.yaml` — every agent's `.env` re-renders with the real values and connects; each host self-registers as a system on first successful handshake.

## Runtime config

`docker/beszel-hub/compose.yaml`: `henrygd/beszel`, joins `caddy-proxy`, exposes `8090` to Caddy, persists `./data` to `/beszel_data`.
`docker/beszel-agent/compose.yaml`: `henrygd/beszel-agent`, `network_mode: host` (required for host-level network interface stats — this also means it doesn't join `caddy-proxy`, since it isn't routed through Caddy at all), and a read-only mount of `/var/run/docker.sock` for container stats.
