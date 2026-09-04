# Wastebin: Custom Image

`quxfoo/wastebin` is `FROM scratch` — no shell, no libc, nothing a Docker
`HEALTHCHECK` can exec, and no `/data` directory of its own. `docker/wastebin/Dockerfile`
adds two things on top, neither changing how the app itself runs:

- `busybox`'s musl-variant statically linked `wget` as `/wget`, for the
  healthcheck (pinned version lives in `docker/wastebin/Dockerfile`,
  not duplicated here).
- An empty, `10001:10001`-owned `/data` directory (`10001` is the image's
  own `app` user — see its README) plus a `VOLUME /data` declaration, so
  the first, empty mount of `compose.yaml`'s `data` volume inherits that
  ownership from the image instead of coming up root-owned. Without
  this, wastebin (forced non-root by `user: 10001:10001` in
  `compose.yaml`, matching the image) can't open its own SQLite database
  file on a fresh volume. This inheritance only happens on a volume's
  first mount — a volume already populated before `user:`/the Dockerfile
  matched `10001:10001` needs a manual one-time `chown -R 10001:10001`
  against it directly; nothing does this automatically.

A GitHub Actions workflow (`.github/workflows/build-wastebin-image.yml`)
builds and pushes the result to `ghcr.io/wenenhoe/wastebin`, tagged by
wastebin version. Hosts pull it like any other app's image — the generic
`compose_app` role has no build step.

Triggers: push to `main` when `docker/wastebin/Dockerfile` changes,
weekly on schedule (catches an upstream `busybox`-musl patch landing
with no Dockerfile text change), and `workflow_dispatch`. Same shape as
`build-caddy-image.yml` — see [`caddy.md`](caddy.md) for the more
heavily-annotated original.
