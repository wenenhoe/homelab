FROM busybox:1.38.0-musl@sha256:80e38f9a1b39188b8bdb28879178edb322a4402b081a9aedda1924609decd6f6 AS data-dir
RUN mkdir -p /data

FROM twinproduction/gatus:v5.38.0@sha256:085ed63da963728965d00a3c78aa6167e3bf135218485b893201758e079e8415

# twinproduction/gatus is FROM scratch, like quxfoo/wastebin: a static
# wget for a healthcheck to exec, and an owned /data for a fresh named
# volume to inherit. docker/wastebin/Dockerfile explains both.
COPY --chmod=755 --from=busybox:1.38.0-musl@sha256:80e38f9a1b39188b8bdb28879178edb322a4402b081a9aedda1924609decd6f6 /bin/wget /wget
COPY --chown=10001:10001 --from=data-dir /data /data
VOLUME /data

# Upstream sets no USER, so without this the container runs as root.
USER 10001:10001
