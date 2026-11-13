# Gatus: Service Record

The job-heartbeat monitor, on `security`. Each scheduled job pushes a heartbeat and Gatus alerts to Telegram when one is missed. The endpoints, tokens and alert topics are in [`gatus.md`](../monitoring/gatus.md); the catalog's facts are in the [coverage table](../disaster-recovery/coverage.md).

## Dependencies

- Needs the `caddy-proxy` network, the `data` and `config` volumes, its rendered config and `.env`, and one token per job plus the dashboard password hash and the Telegram credentials, all from OpenBao ([`gatus.md`](../monitoring/gatus.md#tokens)).
- Needed by the jobs it watches (backups, the cloud relay, certificate renewal and expiry checks, the R2 read watcher). A job that cannot push is silent without it.

## Data

- A SQLite database in `data` with check history and open-incident state. The config holds no secret; the `.env` holds the job tokens, the dashboard hash and the Telegram credentials, and is mode `0600`.

## Exposure

- The route sets `auth: false`, because pushes are `POST`s from systemd units and cron jobs that cannot complete a login. A push is protected by the job's own bearer token, and the dashboard data by Gatus's basic auth ([`gatus.md`](../monitoring/gatus.md)).
- Outbound, it sends alerts to Telegram. It runs as a non-root user with every capability dropped.
- The image is built in this repository from the pinned upstream image ([`gates.md`](../engineering/ci/gates.md)).

## Threat model

- A leaked job token lets someone send a false success for that one job and hide its failure. Tokens are one per job, so a leak affects one.
- The dashboard page shell is served to anyone; the data behind it needs the basic-auth password.
- Unknown: whether the push route can be reached from outside the lab. Check the Caddy and DNS exposure of the route.

## Observability

- Its own endpoint probes `/health` and raises no alert, because Gatus needs at least one regular endpoint ([`gatus.md`](../monitoring/gatus.md)). Beszel reports the container's state.
- Unknown: what notices Gatus itself stopping. A dead monitor produces no missed-heartbeat alert; check for an independent probe of its health.

## Disaster recovery

Not backed up, by design: the history is not needed, and the config and tokens are rebuilt from the repository and OpenBao. Stopping the container to copy the database would restart every heartbeat timer and delay detection ([`gatus.md`](../monitoring/gatus.md#runtime-config)). Recovery tier 3. A new instance shows an endpoint only after its first interval passes. Acceptable loss and downtime: Unknown.

## Lifecycle

- Upgrade: bump the pinned upstream image, and the repository's build of it, then deploy.
- Adding a job is a catalog change in `heartbeat_jobs` plus a token ([`gatus.md`](../monitoring/gatus.md#adding-a-job)).
- Removal: every job's heartbeat then goes unwatched.
- Waits on OpenBao for its tokens at deploy.
