---
id: PROJ-kms-image
title: KMS Image
type: project
status: not-started
blocked: false
summary: Build the Windows activation host's server-only image from the upstream py-kms in this repository, attest it, and replace the 11notes images and the kms-gui app.
decision: ADR-0091/0
allowed_paths:
  - docker/kms/**
  - .github/workflows/build-kms-image.yml
  - .github/renovate.json5
  - tools/ci/images/registry.py
  - tools/ci/provenance/registry.py
  - tools/tests/ci/images/**
  - tools/tests/ci/provenance/**
  - ansible/inventory/group_vars/all/app_catalog.yaml
  - ansible/inventory/host_vars/services.yaml
  - ansible/playbooks/restore.yaml
  - ansible/roles/restore/molecule/default/converge.yml
  - ansible/roles/cloud_sync/molecule/default/converge.yml
  - ansible/roles/restore_discovery/molecule/discovery_and_restore/converge.yml
  - ansible/roles/backup_agent/molecule/default/files/docker/happy_app_stop/compose.yaml
  - docker/dashy/configs/conf.yaml.j2
  - docs/topics/disaster-recovery/backup.md
  - docs/topics/disaster-recovery/restore.md
  - docs/topics/engineering/ci/scheduled-jobs.md
  - docs/topics/engineering/ci/gates.md
---

# KMS Image

Replaces the third-party KMS and KMS GUI images with a server-only image this repository builds from the upstream `py-kms` at a pinned tag and commit, and removes the web interface and the volume behind it, as [ADR 0091 (Activation host image)](../decisions/0091-where-the-activation-hosts-image-comes-from/revision-000.md) decides. It is staged because the image has to be built and proven before the deployment changes, and the deployment change touches the app catalog, the backup and restore docs and the dashboard.

## Scope

The image's Dockerfile in `docker/kms/` and its build workflow `.github/workflows/build-kms-image.yml`, its entries in `tools/ci/images/registry.py` and `tools/ci/provenance/registry.py` with their tests, the Renovate rule in `.github/renovate.json5` that bumps the py-kms tag and its commit together, and the switch of the `kms` app to the new image. That removes the `kms-gui` container, the `kms_data` volume, the backup entry and the route from `ansible/inventory/group_vars/all/app_catalog.yaml` and `ansible/inventory/host_vars/services.yaml`, and the tile from `docker/dashy/configs/conf.yaml.j2`.

The docs that describe `kms` as a stateful app change with it: `docs/topics/disaster-recovery/backup.md`, `docs/topics/disaster-recovery/restore.md`, the example in `ansible/playbooks/restore.yaml`, the schedule table in `docs/topics/engineering/ci/scheduled-jobs.md` and the build list in `docs/topics/engineering/ci/gates.md`. Four Molecule files describe `kms` in a comment as a single-volume app or point at its compose label, which stops being true: `ansible/roles/restore/molecule/default/converge.yml`, `ansible/roles/cloud_sync/molecule/default/converge.yml`, `ansible/roles/restore_discovery/molecule/discovery_and_restore/converge.yml` and `ansible/roles/backup_agent/molecule/default/files/docker/happy_app_stop/compose.yaml`.

Not in this project: how the Windows machines find or activate against the host, the gateway rule that lets their networks reach it, and removing the old volume from the host, which is a manual step recorded in the closing stage. The Molecule fixtures keep `kms` as a name, including the object names in the discovery scenario's verify play, since each scenario defines its own app catalog. The adding-an-app topic doc still names it as an app with a templated compose file, which it stays, and the OpenBao topic doc matches only inside an unrelated word.

## Decision

Implements [ADR 0091 (Activation host image)](../decisions/0091-where-the-activation-hosts-image-comes-from/revision-000.md), still `working`. The project stays `not-started` until that revision is `approved`, and Stage 1 resolves its two assumptions.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Build the image locally and run it in the private `dockerd` harness with upstream's own client against it | Not started | The server runs as a non-root user with every capability dropped, `no-new-privileges` and a read-only root filesystem, restarts cleanly, and answers the client; both of the ADR's assumptions that this harness can settle are recorded |
| 2 | The Dockerfile, the build workflow and the registry entries | Not started | `ghcr.io/wenenhoe/kms` is published from `main`, attested, listed as attested in the provenance registry, with its tag derived from the Dockerfile and a Renovate rule moving the py-kms tag and its commit together |
| 3 | Switch the `kms` app to the new image and remove the interface, the volume, the backup entry, the route and the dashboard tile | Not started | The compose file pins the new image by digest and publishes only `1688/tcp`, the app catalog, host variables, backup and restore docs and dashboard no longer name `kms-gui` or `kms_data`, and a Windows 11 guest activates against the deployed host |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] The image builds from a pinned py-kms tag and fails when the tag resolves to another commit.
- [ ] `ghcr.io/wenenhoe/kms` is attested by this repository's workflow and the provenance check lists it as attested.
- [ ] The container runs as a non-root user with `cap_drop: ALL`, `no-new-privileges:true` and a read-only root filesystem, and restarts cleanly.
- [ ] The `kms` app has no volume, no backup entry, no route and no `kms-gui` container, and the dashboard has no tile for it.
- [ ] A Windows 11 guest activates against the deployed host.
- [ ] `kms_data` is removed from the host and the ADR is `accepted`.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** the ADR's Decision, and the production host's volume, which the maintainer removes.
- **Relevant files and interfaces:** the other `build-*-image.yml` workflows, `ci.images.registry` and the provenance registry for the pattern.
- **Required checks:** `pre-commit run --all-files`, `uv run pytest` from `tools/`, and the compose boot test.

## Risks

- The upstream organisation has two tags and one maintainer line, so a bump may need a commit pin without a tag.
- A Windows 11 build newer than the pinned tag's database may activate differently, which only the Stage 3 guest shows.

## Open items

- Whether the container's log level shows each activation request clearly enough to replace the removed client history.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
