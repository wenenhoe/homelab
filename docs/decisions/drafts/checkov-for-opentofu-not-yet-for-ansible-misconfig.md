# Checkov for OpenTofu when it lands; Trivy stays for Ansible misconfig scanning until then

**Status:** Draft

## Context

[`security-scanning.md`](../../security-scanning.md) documents Trivy's
existing Ansible misconfiguration scanner (`_trivy-scan.yml`), scoped
via `detect-changes` on PRs and unscoped weekly. Making it work at all
against this repo's layout took real, non-obvious engineering — a
`DEFAULT_ROLES_PATH` env var (Trivy's ansible scanner never reads
`ansible.cfg`'s `roles_path`), and a hand-generated `ansible.playbooks`
list (Trivy's own playbook auto-discovery is non-recursive and never
finds anything under `playbooks/`) — both confirmed against Trivy's
source and documented inline in `_trivy-scan.yml`.

[`projects/tofu-vm-provisioning.md`](../../projects/tofu-vm-provisioning.md)
already carries `checkov` (IaC scanning) for the OpenTofu code as an
open item, not yet scoped — Stage 1 (the Tofu project skeleton) hasn't
landed. Checkov supports both Ansible and Terraform/OpenTofu as
first-class frameworks in one tool, raising a second question ahead of
that: whether to consolidate onto it for Ansible now too, rather than
running two scanners once Tofu code exists.

A one-off comparison was run against this repo's real `ansible/` tree
(13 playbooks, 26 roles) to ground that second question in this repo's
findings rather than the tools' general reputations:

- Trivy's ansible-specific checks are not embedded in its binary —
  they're fetched at scan time from an OCI registry
  (`mirror.gcr.io/aquasec/trivy-checks`). With that host unreachable,
  Trivy fell back to embedded-only checks and reported zero
  misconfigurations across a correctly-parsed 331-task role graph —
  not an error, a silent "clean" result. Whether this repo's actual CI
  runners reach that host successfully (GitHub-hosted runners have
  normal internet access, unlike the sandbox this was tested in) is
  unconfirmed from the workflow's own run logs.
- Checkov ran fully self-contained, no runtime network dependency,
  ~6s cold on this repo's `ansible/` tree. It surfaced 23 findings
  across only two check IDs: `CKV2_ANSIBLE_1` ("HTTPS url used with
  uri") and `CKV2_ANSIBLE_3` ("block handles task errors").
- At least one `CKV2_ANSIBLE_1` finding is a confirmed false positive:
  `secrets/tasks/vault_login.yaml`'s `secrets_vault_base_url` is a
  hardcoded `https://` scheme with a Jinja-templated hostname
  (`"https://openbao.{{ hostvars[...].caddy_domain }}:{{ ... }}"`) —
  Checkov can't resolve the template and flags it anyway.
- By default, Checkov scans every YAML file under `ansible/` as
  candidate Ansible content, including `roles/*/molecule/*/converge.yml`
  and `verify.yml` test fixtures — roughly 14 of the 23 findings are
  `CKV2_ANSIBLE_3` hits inside those fixtures. Trivy's current scope is
  narrower by design (the 13 real playbooks plus their resolved role
  graph only), matching this repo's existing "test scaffolding isn't
  production automation" line drawn elsewhere (`ansible/tests/` is
  covered by `pytest`, not `ansible-lint`'s repo-wide sweep, for the
  same reason).

## Decision

Keep Trivy for Ansible misconfig scanning as-is; do not introduce
Checkov for Ansible now.

Adopt Checkov specifically once the project's Stage 1 lands real
OpenTofu code — that's Checkov's actual value case here, and it needs
no separate Ansible-only justification. At that point, extend the
same Checkov setup to also cover `ansible/`, retiring Trivy's
`ansible-misconfig-scan` job in the same change — one migration
instead of two, informed by the false-positive and test-fixture-scope
findings above rather than rediscovering them.

Trivy's secret-scan job is unaffected either way; this decision is
scoped to the ansible misconfig scanner only.

## Assumptions

- **Claim:** Checkov's OpenTofu support is equivalent to its Terraform
  support (same HCL parsing regardless of which binary generated the
  state), so "adopt Checkov for Tofu" doesn't need its own separate
  evaluation once Tofu code exists.
  **Breaks if wrong:** the "one tool covers both stages" reasoning
  weakens if Tofu-specific parsing gaps exist; the migration might
  need to special-case Tofu the same way Ansible needed
  `DEFAULT_ROLES_PATH`.
  **Checked by:** a spike against the real Tofu code once the
  project's Stage 1 lands.
- **Claim:** the `CKV2_ANSIBLE_1` template false positive and the
  Molecule-fixture default scope are both addressable via Checkov's
  own config (`--skip-check`, `--skip-path`/`.checkov.yaml`), not
  fundamental limitations.
  **Breaks if wrong:** the eventual combined migration carries more
  ongoing noise than expected, or needs a custom check/suppression
  scheme instead of stock config.
  **Checked by:** a spike at migration time against this repo's actual
  fixture layout and templated-URL patterns.
- **Claim:** this repo's live CI actually reaches
  `mirror.gcr.io` and Trivy's ansible scan is producing real findings
  today, not silently falling back to a checks-less "clean" result.
  **Breaks if wrong:** the status quo this decision holds onto isn't
  actually providing coverage, independent of the Checkov question.
  **Checked by:** manually checking a recent `ansible-misconfig-scan`
  run's logs for a successful "Downloading checks bundle" versus a
  "Falling back to embedded checks" message — a separate, immediate
  task, not gated on this decision.

## Consequences

- No CI change from this decision; `_trivy-scan.yml` and
  `security-scanning.md` stay as-is.
- The `mirror.gcr.io` reachability question above is real and
  independent of Checkov, but tracked here rather than acted on —
  worth raising as its own task regardless of how this draft resolves.
- Whoever picks up Stage 1 should re-run this comparison fresh rather
  than trust these numbers as still current — tool versions and rule
  sets will have moved on by then.
