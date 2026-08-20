# Pre-bakes what molecule_helpers/playbooks/prepare_dind.yml otherwise
# installs fresh on every Molecule run: Docker Engine, the fuse-overlayfs
# storage driver, and python3-requests. Mirrors, but does not invoke,
# ansible/roles/docker/tasks/main.yaml — that role also enables+starts the
# systemd unit, which needs a running init system `docker build` doesn't
# have. Update both files together if the docker role's package list or
# apt-repo setup changes; there is no automated check for this drift yet.
#
# docker-ce's postinst enables the unit via debian's systemd triggers
# regardless of whether systemd is PID 1 at install time, so an explicit
# `systemctl enable` isn't needed here — verify with
# `systemctl is-enabled docker` after boot (see docs/molecule-dind-image.md).
#
# NOT used by ansible/roles/docker's own Molecule scenario, which tests
# that installation from a clean image — baking Docker in here would make
# that test tautological.
FROM geerlingguy/docker-ubuntu2604-ansible:latest

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        python3-debian \
        python3-requests \
        fuse-overlayfs \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && . /etc/os-release \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        docker-ce \
        docker-ce-cli \
        containerd.io \
        docker-buildx-plugin \
        docker-compose-plugin \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Baked as the default so scenarios that don't manage their own
# daemon.json (everything except bind9) get it for free. bind9's own
# prepare.yml overwrites this file for its DNS settings and sets the
# storage driver via a systemd drop-in instead — see that file's comment.
RUN mkdir -p /etc/docker \
    && printf '{\n  "storage-driver": "fuse-overlayfs"\n}\n' > /etc/docker/daemon.json
