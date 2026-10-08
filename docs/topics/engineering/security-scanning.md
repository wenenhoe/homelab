# Security Scanning

Trivy checks, separate from the [PR-checks pipeline](ci/pipeline.md)'s
correctness/linting jobs — these are report-only, not merge-blocking. Image
vulnerabilities are assessed by a separate program, described
[last](#image-vulnerability-assessment).

## Trivy security scans

Two checks, defined once in
[`_trivy-scan.yml`](../../../.github/workflows/_trivy-scan.yml) (`workflow_call`,
same sharing pattern as `_compose-boot-test.yml`) and run from two
places:

- `pr-checks.yml`'s `trivy-scan` job — Ansible misconfig scoped via
  `detect-changes` (`trivy_ansible`); the secret scan runs
  unconditionally on every PR, the same reasoning as `pre-commit-checks`
  (a leaked secret can land in any file) — a second, independent
  backstop alongside `gitleaks`, which `pre-commit-checks` already runs
  unconditionally.
- `trivy-scheduled.yml` — both, weekly, unscoped, so a new misconfig
  check added to Trivy itself still gets caught even when nothing in
  this repo changed.

| Check | Target | Notes |
| :--- | :--- | :--- |
| Ansible misconfig | `ansible/` (Trivy's ansible scanner auto-detects the project root via `ansible.cfg`, `roles/`, `playbooks/`, etc.) | `--misconfig-scanners ansible` only, via an inline `trivy.yaml` (`misconfiguration.scanners`) — trivy-action has no first-class input for this flag |
| Secrets | Whole repo (`trivy fs --scanners secret`) | Second, independent backstop alongside `gitleaks` (already unconditional in `pre-commit-checks`) |

**Report-only**: both jobs set `exit-code: '0'` — findings surface in
the Security tab but never block a PR.

**Accepted-risk findings**: [`.config/.trivyignore`](../../../.config/.trivyignore),
alongside this repo's other tool configs — same documented-exception
convention as `.github/compose-boot-test-exclusions.txt`.

**Two Trivy Ansible-scanner quirks** (a Trivy version bump may change them):

- It never reads `ansible.cfg`'s `roles_path` (`resolveRolePath` only
  checks a `roles/` dir next to the playbook, or `DEFAULT_ROLES_PATH`).
  This repo's roles are a sibling of `ansible/playbooks/`, not nested
  under it, so without `DEFAULT_ROLES_PATH` every `include_role`/`roles:`
  silently fails to resolve and the scan passes clean while covering
  almost none of the real task content.
- Playbook auto-discovery (`resolvePlaybooksPaths`) is a non-recursive
  `ReadDir()` on the project root, so it never finds anything under
  `playbooks/`. Worked around with an explicit `ansible.playbooks` list
  in the generated Trivy config, built from the live
  `ansible/playbooks/*.y{a,}ml` listing so new playbooks are covered
  automatically. That is
  [`tools/ci/scan/trivy_config.py`](../../../tools/ci/scan/trivy_config.py),
  which fails the job if the directory has no playbooks rather than
  scanning nothing.

With both fixed, this repo currently scans clean — expected: Trivy's
Ansible module analysis only checks cloud-resource modules, and this
repo's roles use `community.docker`/`ansible.posix`/`ansible.builtin.*`
exclusively. The job is still the regression backstop it was scoped as —
it would catch a misconfigured cloud module if one is ever added.

## Why no image CVE scanning

Image CVE scanning doesn't run in this repo's CI, for two reasons.

- **Where a result can live.** A scan result says which deployed image has
  which fixable vulnerability, and this repo's commits, pull requests, issues
  and Actions logs are public ([`docs/README.md#public-repo`](../../README.md#public-repo)).
  Findings belong in the private tracker.
- **The first attempt was noise.** It was tried in several scopes (PR-triggered,
  diff-aware, unconditional) with a Vulnerability Dashboard issue to aggregate
  the results, and dropped because most of what it reported was third-party
  images awaiting an upstream rebuild, which nothing here can act on. It also
  scanned only a subset: it found images with a `compose*.yaml` glob, which
  skips the templated compose files and every image pinned in Ansible.

Ansible misconfig and secrets don't have the noise problem (a finding in
either is fixable here), so those stayed. Images are assessed by the program
below, over a complete inventory.

## Image vulnerability assessment

A weekly job in the private `homelab-security` repo's own CI scans every image
this repo deploys, ranks what it finds, and keeps the results there. It is
decided in
[ADR 0071 (Image vulnerability assessment)](../../decisions/0071-assessing-the-vulnerabilities-of-deployed-container-images/revision-000.md).
This repo's part is the inventory it reads and the rule that no result lands
here.

- **Inventory.** The job reads this repo by a plain clone and runs
  `python -m ci.images.remote list --json`
  ([the contract](ci/gates.md#image-inventory-json)). An image pinned in a
  compose file, an Ansible role or a script is **deployed** and scanned. A
  Dockerfile base is covered through the image built from it. An image used
  only by Molecule or CI is listed and not scanned.
- **Ranking.** An image's priority band comes from how reachable it is and what
  its compromise would grant. Reachability is derived from this repo's own
  configuration, from the point of view of anything already on the LAN or
  tailnet: a route marked `auth: false`, a published port that isn't bound to
  loopback, or host networking makes an image reachable without logging in, and
  a Tinyauth-protected route makes it reachable after. Consequence is a judgment
  kept in the private repo's policy file, where an image nobody has classified
  ranks as high.
- **Where it runs.** Three jobs. The one that runs code from this repo and the
  one that scans hold read-only tokens; only the job that records results can
  write. Results, the policy and accepted-risk records stay in the private repo,
  which notifies by pull request when something needs attention.
- **Coupled to this repo's shape.** Classification reads each app's `routes`
  (`upstream`, `auth`) in `app_catalog.yaml` and each compose service's `ports`,
  `network_mode` and `container_name`. A change to those shapes shows up there
  as images it can't classify, which rank top band, not as silence.
- **Not covered.** Host operating-system packages, whether what runs matches
  what `main` declares, and whether a vulnerability is exploitable here. A fixed
  package version doesn't mean a published image carries the fix, so a finding
  can count as fixable while nothing published fixes it.
