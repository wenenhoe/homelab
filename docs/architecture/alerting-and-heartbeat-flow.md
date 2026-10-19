# Alerting and Heartbeat Flow

Where a failure alert or a missed-job heartbeat ends up — spans
[`telegram-notifications.md`](../topics/monitoring/telegram-notifications.md),
[`uptime-kuma.md`](../topics/monitoring/uptime-kuma.md) and [`beszel.md`](../topics/monitoring/beszel.md), none of which
shows both paths together. Two paths exist because they catch different things: a unit's `OnFailure=` reports
a failure when one happens, and a push monitor reports silence when nothing runs at all.

```mermaid
flowchart LR
    subgraph sources["Failure alerts, sent when something fails"]
        beszel["Beszel hub<br/>host and container state"]
        dvb["docker-volume-backup<br/>backup job failures"]
        sync["cloud-sync.service<br/>OnFailure"]
        renew["cert-renewer@<br/>OnFailure"]
        expiry["cert-expiry-check<br/>OnFailure"]
    end

    subgraph push["Heartbeats, sent on success only"]
        psync["cloud-sync success"]
        prenew["cert-renewer-heartbeat@<br/>daily, cert not near expiry"]
        pexpiry["cert-expiry-check success"]
        pfresh["backup freshness check<br/>all apps fresh"]
        pwatch["R2 watcher heartbeat timer"]
    end

    kuma["Uptime Kuma<br/>push monitors"]
    gatus["Gatus<br/>external endpoints"]

    subgraph topics["Telegram topics"]
        monitoring["Monitoring"]
        backups["Backups"]
        certs["Certs"]
    end

    beszel --> monitoring
    dvb --> backups
    sync --> backups
    renew --> certs
    expiry --> certs

    psync --> kuma
    prenew --> kuma
    pexpiry --> kuma
    pfresh --> kuma
    pwatch --> kuma
    psync & prenew & pexpiry & pfresh & pwatch --> gatus
    kuma -. "missed heartbeat,<br/>the monitor's topic" .-> topics
    gatus -. "missed heartbeat,<br/>the group's topic" .-> topics
```

During the parallel run every producer pushes to both monitors. A skipped `cert-renewer@` run (certificate not yet due) is neither a failure nor a success, so it sends nothing on
either path; its heartbeat is a separate daily liveness push, sent only while the certificate has more than 72 hours left.
Shoutrrr senders (Beszel,
`docker-volume-backup`) take `chat_id:topic_id` in one string; the systemd notifiers call Telegram's API with
separate `chat_id` and `message_thread_id`, as
[`telegram-notifications.md`](../topics/monitoring/telegram-notifications.md) explains.
