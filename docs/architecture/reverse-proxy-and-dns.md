# Reverse Proxy & DNS

How a hostname actually resolves and reaches the right host — spans
[`caddy.md`](../caddy.md) (per-host reverse proxy, TLS) and
[`bind9.md`](../bind9.md) (the one shared internal DNS server), neither
of which shows the two working together end to end.

```mermaid
flowchart LR
    client(["LAN client"])

    subgraph services["services"]
        bind9["BIND9<br/>(authoritative, non-recursive,<br/>one zone per app host)"]
    end

    subgraph anyhost["Any app host<br/>(services / play / security / storage)"]
        caddy["Caddy<br/>wildcard vhost per host,<br/>one handle block per app"]
        app[("Routed app")]
    end

    ddns["OPNsense DDNS"]
    do[("DigitalOcean DNS<br/>(DNS-01 challenge)")]

    client -- "1 . query app.&lt;caddy_domain&gt;" --> bind9
    bind9 -- "2 . CNAME to this host's<br/>dns_ddns_target" --> ddns
    ddns -- "3 . resolves to<br/>the host's real IP" --> client
    client -- "4 . connects directly" --> caddy
    caddy -- "5 . matched handle block" --> app
    do -. "DNS-01 challenge,<br/>once per host's wildcard cert" .-> caddy
```

Every app host declares its own `dns_zones` in `host_vars` (usually
just its own `caddy_domain`); BIND9 only aggregates and serves what
each host already declared — see
[`bind9.md`](../bind9.md#how-zone-data-is-gathered). The CNAME in step
2 is auto-generated for every app with a `caddy` route, from the same
`host_vars` entry that gives it its Caddy routing rule — one place
to add an app gets it both. See
[`host-vars.md`](../host-vars.md#caddy_domain).
