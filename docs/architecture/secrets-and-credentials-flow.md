# Secrets & Credentials Flow

How `controller` reaches OpenBao day-to-day, and how cloud credential
rotation plus the R2 per-read watcher fit together — spans
[`openbao-auth.md`](../openbao-auth.md) (`controller`'s AppRole),
[`cloud-credential-creation.md`](../cloud-credential-creation.md)
(minting/rotating R2/B2/OCI credentials), and
[`openbao-r2-read-watcher.md`](../openbao-r2-read-watcher.md) (the
per-read alert on the R2 admin token), none of which shows the whole
picture on one page.

## Day-to-day secrets fetch

```mermaid
flowchart LR
    controller(["controller<br/>role_id/secret_id cached locally,<br/>no CIDR bind"])

    subgraph security["security"]
        openbao[("OpenBao<br/>KV v2: secret/data/*")]
    end

    controller -- "1 . AppRole login" --> openbao
    openbao -- "2 . scoped token,<br/>1h TTL" --> controller
    controller -- "3 . kv put/get:<br/>hosts/*,<br/>cloud_credentials/{leaf,rotation}/*" --> openbao
```

Every `ansible-playbook deploy.yaml` run and every
`ansible/cloud_credentials/*.py` invocation authenticates this way.
`controller`'s AppRole has no CIDR bind — a laptop has no stable
address to bind to
([ADR 0020](../decisions/0020-controller-single-broad-approle-not-split-by-consumer.md)).

## Cloud credential rotation & the R2 read-watcher

```mermaid
flowchart LR
    controller(["controller<br/>ansible/cloud_credentials/*.py,<br/>run by hand"])
    r2[("Cloudflare R2")]
    b2[("Backblaze B2")]
    oci[("OCI Object Storage")]

    subgraph security["security"]
        openbao[("OpenBao<br/>cloud_credentials/rotation/*,<br/>incl. the R2 admin token")]
        watcher["r2-read-watcher<br/>own least-privilege AppRole,<br/>tails openbao's audit log"]
    end

    telegram(["Telegram"])
    kuma(["Uptime Kuma<br/>heartbeat"])

    controller -- "1 . mint/rotate<br/>leaf & rotation keys" --> r2 & b2 & oci
    controller -- "2 . cache result" --> openbao
    openbao -. "3 . any read of the<br/>R2 rotation token path" .-> watcher
    watcher -- "4 . alert" --> telegram
    watcher -- "heartbeat" --> kuma
```

The R2 admin token is the one rotation credential accepted as
master-equivalent rather than narrowly scoped — Cloudflare's API can't
mint a scoped delegate for it
([ADR 0014](../decisions/0014-r2-rotation-token-accepted-as-master-equivalent.md)).
The read-watcher's per-read alert on that one path is the compensating
control, running its own least-privilege AppRole
([ADR 0026](../decisions/0026-openbao-audit-device-and-r2-per-read-watcher.md))
rather than reusing `controller`'s broader one — a compromised
`controller` AppRole still can't read that path silently.
