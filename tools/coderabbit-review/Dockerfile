# Based on rikatz's coderabbit-cli-docker gist:
# https://gist.github.com/rikatz/1135c311d86306a5bff3e39276968b17
FROM ubuntu:26.04 AS fetch

# The CLI is pinned by version and by the sha256 of its linux-x64 zip, taken
# from that release's SHA256SUMS; docs/coderabbit-review.md has the bump steps.
ARG CODERABBIT_VERSION=0.8.0
ARG CODERABBIT_SHA256=0000000000000000000000000000000000000000000000000000000000000000

# hadolint ignore=DL3008 # operator tooling, not a deployed app — unpinned by design.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /dl
# unzip runs only once the hash matches.
RUN curl -fsSLo coderabbit-linux-x64.zip \
      "https://cli.coderabbit.ai/releases/${CODERABBIT_VERSION}/coderabbit-linux-x64.zip" \
    && printf '%s  coderabbit-linux-x64.zip\n' "${CODERABBIT_SHA256}" > SHA256SUMS \
    && sha256sum -c SHA256SUMS \
    && unzip -q coderabbit-linux-x64.zip coderabbit

FROM ubuntu:26.04

# hadolint ignore=DL3008 # same reasoning as the fetch stage above.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system --add safe.directory /workdir \
    && useradd -l -u 1001 -m coderabbit \
    && chmod 1777 /home/coderabbit \
    && mkdir /workdir

COPY --from=fetch --chmod=0755 /dl/coderabbit /bin/coderabbit

# No build-time UID: coderabbit-review.sh runs the container with
# `docker run -u <invoking uid>:<gid>`, so the CLI's home must be writable
# by a UID this image has no passwd entry for (hence the sticky, world-
# writable home) and HOME is pinned to it, since the $AUTH_DIR mount lives
# there. `USER` is only the non-root default when the script isn't used.
ENV HOME=/home/coderabbit
USER 1001
WORKDIR /workdir
ENTRYPOINT ["/bin/coderabbit"]
