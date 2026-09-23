# Based on rikatz's coderabbit-cli-docker gist:
# https://gist.github.com/rikatz/1135c311d86306a5bff3e39276968b17
FROM fedora:43

ARG USER_UID=1001

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
    && useradd -l -u "${USER_UID}" -m coderabbit \
    && mkdir /workdir && chown -R "${USER_UID}" /workdir \
    && dnf clean all

USER ${USER_UID}

WORKDIR /workdir
ENTRYPOINT ["/bin/coderabbit"]
