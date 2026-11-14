# Coverage: What Each App Has

For each app in the catalog: where it runs, the volumes it holds, how it is
reached, what is backed up and when, which service record describes it, and
its recovery tier ([`exercises.md`](exercises.md)). A `—` in the Record column
means the app has no record yet.

The table is generated from the catalog and the inventory by
`generate-doc-indexes`. Don't edit it by hand: change the source and
regenerate. The view shows no result of any exercise.

## Apps

| App | Hosts | Volumes | Routes | Backup | Record | Tier |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `caddy` | services, play, security, storage | `caddyfile`, `data`, `config` | — | — | [caddy.md](../records/caddy.md) | 3 |
| `beszel-hub` | security | `data` | `default` (no Tinyauth) | data at `30 4 * * *` | [beszel-hub.md](../records/beszel-hub.md) | 2 |
| `beszel-agent` | services, play, security, storage | `data` | — | — | [beszel-agent.md](../records/beszel-agent.md) | 3 |
| `bind9` | services, storage | `config`, `cache`, `records`, `run` | — | — | [bind9.md](../records/bind9.md) | 3 |
| `bentopdf` | services | — | `default` (Tinyauth) | — | [bentopdf.md](../records/bentopdf.md) | 3 |
| `cobalt` | services | — | `default` (no Tinyauth) | — | [cobalt.md](../records/cobalt.md) | 3 |
| `dashy` | services | `data` | `default` (Tinyauth) | — | [dashy.md](../records/dashy.md) | 3 |
| `kms` | services | `data` | `default` (Tinyauth) | data at `30 4 * * *` | [kms.md](../records/kms.md) | 2 |
| `librespeed` | services | — | `default` (Tinyauth) | — | [librespeed.md](../records/librespeed.md) | 3 |
| `shlink` | services | — | `short` (Tinyauth), `web` (Tinyauth) | — | [shlink.md](../records/shlink.md) | 3 |
| `seaweedfs` | storage | `data` | `s3` (no Tinyauth), `filer` (Tinyauth) | — | [seaweedfs.md](../records/seaweedfs.md) | 1 |
| `wastebin` | services | `data` | `default` (Tinyauth) | data at `30 4 * * *` | [wastebin.md](../records/wastebin.md) | 2 |
| `tinyauth` | security | `data` | — | data at `30 4 * * *` | [tinyauth.md](../records/tinyauth.md) | 2 |
| `lldap` | security | `data`, `certs` | `default` (no Tinyauth) | data, certs at `30 4 * * *` | [lldap.md](../records/lldap.md) | 2 |
| `step-ca` | security | `data`, `scripts` | — | data at `30 4 * * *` | [step-ca.md](../records/step-ca.md) | 1 |
| `openbao` | security | `data`, `config`, `certs` | — | — | [openbao.md](../records/openbao.md) | 1 |
| `minecraft` | play | `data`, `backups`, `bluemap_config`, `bluemap_web`, `bluemap_data`, `extras` | `default` (Tinyauth) | backups at `30 4 * * *` | [minecraft.md](../records/minecraft.md) | 2 |
| `gatus` | security | `data`, `config` | `default` (no Tinyauth) | — | [gatus.md](../records/gatus.md) | 3 |
