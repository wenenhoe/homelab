FROM busybox:1.38.0-musl@sha256:119bdf19f884fb540a02b02534632c16525266957572e85996e377d5d41d3168 AS data-dir
RUN mkdir -p /data

FROM twinproduction/gatus:v5.37.0@sha256:094eb186e55235db367e90e9d56140e5897b7044c41de23cde4cc18e6da1242e

# twinproduction/gatus is FROM scratch, like quxfoo/wastebin: a static
# wget for a healthcheck to exec, and an owned /data for a fresh named
# volume to inherit. docker/wastebin/Dockerfile explains both.
COPY --chmod=755 --from=busybox:1.38.0-musl@sha256:119bdf19f884fb540a02b02534632c16525266957572e85996e377d5d41d3168 /bin/wget /wget
COPY --chown=10001:10001 --from=data-dir /data /data
VOLUME /data

# Upstream sets no USER, so without this the container runs as root.
USER 10001:10001
