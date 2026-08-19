FROM quxfoo/wastebin:3.7.2

# quxfoo/wastebin is FROM scratch — no shell, no libc, nothing a
# HEALTHCHECK can exec. busybox:musl's wget is a single statically
# linked binary, so it copies in without pulling in a shell or libc.
COPY --chmod=755 --from=busybox:1.37.0-musl /bin/wget /wget
