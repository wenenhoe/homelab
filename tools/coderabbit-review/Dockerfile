# Based on rikatz's coderabbit-cli-docker gist:
# https://gist.github.com/rikatz/1135c311d86306a5bff3e39276968b17
FROM fedora:43

# CI=true (below) skips the installer's interactive "sign in now?" prompt,
# per install.sh's own documented CI variable. A `docker build` RUN step has
# no controlling terminal, so leaving this unset risks the installer's
# /dev/tty check aborting the script instead of falling through cleanly.
# hadolint ignore=DL3041 # operator tooling, not a deployed app — unpinned by design, mirrors docker/molecule-dind/Dockerfile's own DL3008 ignore for the same reason.
RUN dnf -y install unzip git \
    && curl -fsSL https://cli.coderabbit.ai/install.sh > /tmp/coderabbit.sh \
    && CI=true /bin/sh /tmp/coderabbit.sh \
    && mv "$HOME/.local/bin/coderabbit" /bin/coderabbit \
    && git config --system --add safe.directory /workdir \
    && useradd -l -u 1001 -m coderabbit \
    && chmod 1777 /home/coderabbit \
    && mkdir /workdir \
    && dnf clean all

# No build-time UID: coderabbit-review.sh runs the container with
# `docker run -u <invoking uid>:<gid>`, so the CLI's home must be writable
# by a UID this image has no passwd entry for (hence the sticky, world-
# writable home) and HOME is pinned to it, since the $AUTH_DIR mount lives
# there. `USER` is only the non-root default when the script isn't used.
# Set after the RUN above, whose installer step needs root's own HOME.
ENV HOME=/home/coderabbit
USER 1001

WORKDIR /workdir
ENTRYPOINT ["/bin/coderabbit"]
