# Coverage: What Each App Has and Whether a Restore Was Proven

For each app in the catalog: where it runs, the volumes it holds, how it is
reached, what is backed up and when, which service record describes it, and
the newest [fire drill](fire-drill.md) that restored it. A `—` in the Record
column means the app has no record yet; a `—` in the drill column means no
drill has restored it.

The table is generated from the catalog, the inventory and the fire-drill
results table by `generate-doc-indexes`. Don't edit it by hand: change the
source, or the "Apps covered" cell of a drill row (a catalog app key, or
`None` when the drill restored no app), and regenerate.

## Apps

| App | Hosts | Volumes | Routes | Backup | Record | Newest restoring drill |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `caddy` | services, play, security, storage | `caddyfile`, `data`, `config` | — | — | — | — |
| `beszel-hub` | security | `data` | `default` (no Tinyauth) | data at `30 4 * * *` | [beszel-hub.md](../records/beszel-hub.md) | 2026-11-02 |
| `beszel-agent` | services, play, security, storage | `data` | — | — | [beszel-agent.md](../records/beszel-agent.md) | — |
| `bind9` | services, storage | `config`, `cache`, `records`, `run` | — | — | [bind9.md](../records/bind9.md) | — |
| `bentopdf` | services | — | `default` (Tinyauth) | — | — | — |
| `cobalt` | services | — | `default` (no Tinyauth) | — | — | — |
| `dashy` | services | `data` | `default` (Tinyauth) | — | — | — |
| `kms` | services | `data` | `default` (Tinyauth) | data at `30 4 * * *` | — | 2026-11-06 |
| `librespeed` | services | — | `default` (Tinyauth) | — | — | — |
| `shlink` | services | — | `short` (Tinyauth), `web` (Tinyauth) | — | — | — |
| `seaweedfs` | storage | `data` | `s3` (no Tinyauth), `filer` (Tinyauth) | — | [seaweedfs.md](../records/seaweedfs.md) | — |
| `wastebin` | services | `data` | `default` (Tinyauth) | data at `30 4 * * *` | — | 2026-11-06 |
| `tinyauth` | security | `data` | — | data at `30 4 * * *` | [tinyauth.md](../records/tinyauth.md) | 2026-11-02 |
| `lldap` | security | `data`, `certs` | `default` (no Tinyauth) | data, certs at `30 4 * * *` | [lldap.md](../records/lldap.md) | 2026-11-02 |
| `step-ca` | security | `data`, `scripts` | — | data at `30 4 * * *` | [step-ca.md](../records/step-ca.md) | 2026-11-02 |
| `openbao` | security | `data`, `config`, `certs` | — | — | [openbao.md](../records/openbao.md) | 2026-11-02 |
| `minecraft` | play | `data`, `backups`, `bluemap_config`, `bluemap_web`, `bluemap_data`, `extras` | `default` (Tinyauth) | backups at `30 4 * * *` | — | 2026-11-01 |
| `gatus` | security | `data`, `config` | `default` (no Tinyauth) | — | [gatus.md](../records/gatus.md) | — |
