# Security Scanning

Trivy checks, separate from the [PR-checks pipeline](ci.md)'s
correctness/linting jobs — these are report-only, not merge-blocking.

## Trivy security scans

Two checks, defined once in
[`_trivy-scan.yml`](../.github/workflows/_trivy-scan.yml) (`workflow_call`,
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

**Accepted-risk findings**: [`.config/.trivyignore`](../.config/.trivyignore),
alongside this repo's other tool configs — same documented-exception
convention as `.github/compose-boot-test-exclusions.txt`.

**Two confirmed Trivy Ansible-scanner quirks** (v0.73.0; re-verify if a
version bump ever changes this):

- It never reads `ansible.cfg`'s `roles_path` (`resolveRolePath` only
  checks a `roles/` dir next to the playbook, or `DEFAULT_ROLES_PATH`).
  This repo's roles are a sibling of `ansible/playbooks/`, not nested
  under it, so without `DEFAULT_ROLES_PATH` every `include_role`/`roles:`
  silently fails to resolve and the scan passes clean while covering
  almost none of the real task content.
- Playbook auto-discovery (`resolvePlaybooksPaths`) is a non-recursive
  `ReadDir()` on the project root, so it never finds anything under
  `playbooks/`. Worked around with an explicit `ansible.playbooks` list
  in the generated `trivy.yaml`, built from the live
  `ansible/playbooks/*.y{a,}ml` listing so new playbooks are covered
  automatically.

With both fixed, this repo currently scans clean — expected: Trivy's
Ansible module analysis only checks cloud-resource modules, and this
repo's roles use `community.docker`/`ansible.posix`/`ansible.builtin.*`
exclusively. The job is still the regression backstop it was scoped as —
it would catch a misconfigured cloud module if one is ever added.

## Why no image CVE scanning

Dropped after trying several scopes (PR-triggered, diff-aware,
unconditional) and a Vulnerability Dashboard issue to aggregate
results. In a real scan, the overwhelming majority of findings were
third-party images awaiting an upstream rebuild — not actionable from
this repo regardless of scan frequency or presentation. Ansible
misconfig and secrets don't have that problem (a finding in either is
fixable here), so those stayed.

For occasional visibility without reintroducing standing CI cost, run
Trivy by hand against `docker/**/compose*.yaml`.
