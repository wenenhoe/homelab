# Shlink: Service Record

A URL shortener with its web client, on `services`. The catalog's facts are in the [coverage table](../disaster-recovery/coverage.md); there is no other topic doc for it.

## Dependencies

- Needs the `caddy-proxy` network, two routes (the short domain and the web client) and a `.env` with its API key, which comes from OpenBao.
- The web client needs the server's URL and the same API key. Needed by nothing else.

## Data

- The short links and their visit statistics. Unknown: where they are stored. The catalog declares no volume and the compose file sets no database, so Shlink's default embedded database would live in the container's filesystem and not survive a recreation. Check the container's configuration before relying on the links.
- The API key is a secret; the web client holds it in its environment.

## Exposure

- Both routes are behind Tinyauth, including the short domain, so a short link works only for someone who is logged in.
- The web client carries the API key, so anyone who reaches it has full control of the server.
- Both containers drop every capability and expose port 8080 to Caddy only.

## Threat model

- Whoever reaches the web client controls every link, and the key is in its environment. Tinyauth is the only gate on it.
- Redirects could be changed to point at a malicious address by an authenticated user.

## Observability

- Each container has a health check, and Beszel reports their state ([`beszel.md`](../monitoring/beszel.md)). Nothing checks that a short link resolves.

## Disaster recovery

Not backed up; recovery tier 3. Unknown: whether any links exist that would be lost; see the Data section. A deploy rebuilds the containers.

## Lifecycle

- Upgrade: bump the pinned server and web client tags and deploy. Unknown: whether a server upgrade migrates its database in place; check the release notes.
- Removal: delete its catalog entry and run `cleanup.yaml` ([`cleanup.md`](../deploy/cleanup.md)).
- Waits on the server before the web client.
