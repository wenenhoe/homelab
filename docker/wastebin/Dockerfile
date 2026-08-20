FROM busybox:1.38.0-musl AS data-dir
RUN mkdir -p /data

FROM quxfoo/wastebin:3.7.2

# quxfoo/wastebin is FROM scratch — no shell, no libc, nothing a
# HEALTHCHECK can exec. busybox:musl's wget is a single statically
# linked binary, so it copies in without pulling in a shell or libc.
COPY --chmod=755 --from=busybox:1.38.0-musl /bin/wget /wget

# The image's own USER is app:app (UID/GID 10001, see its Dockerfile
# and README — "Make sure the ./data folder is writable by the user
# 10001") but never creates /data itself, so a fresh named volume
# mounts in root-owned and wastebin can't open its database file.
# Docker copies an image directory's content (ownership included) into
# a named volume that's still empty on first mount — pre-creating an
# owned, empty /data here means that first mount comes up writable
# without needing a shell inside this image to chown it after the fact.
COPY --chown=10001:10001 --from=data-dir /data /data
VOLUME /data
