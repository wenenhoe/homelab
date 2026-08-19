# Wastebin: Custom Image

`quxfoo/wastebin` is `FROM scratch` — no shell, no libc, nothing a Docker
`HEALTHCHECK` can exec. `docker/wastebin/Dockerfile` copies in
`busybox:1.37.0-musl`'s statically linked `wget` as `/wget` for that
purpose only; nothing else about the image changes. A GitHub Actions
workflow (`.github/workflows/build-wastebin-image.yml`) builds and
pushes it to `ghcr.io/wenenhoe/wastebin`, tagged by wastebin version.
Hosts pull it like any other app's image — the generic `compose_app`
role has no build step.

Triggers: push to `main` when `docker/wastebin/Dockerfile` changes,
weekly on schedule (catches a `busybox:1.37.0-musl` patch landing with
no Dockerfile text change), and `workflow_dispatch`. Same shape as
`build-caddy-image.yml` — see [`caddy.md`](caddy.md) for the more
heavily-annotated original.
